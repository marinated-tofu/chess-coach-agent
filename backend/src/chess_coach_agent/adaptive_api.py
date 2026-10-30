from __future__ import annotations

import asyncio
import time

import httpx
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from .accounts import Viewer, can_access, public_profile, require_access, require_player
from .coach_limits import QuotaCharge, limit_notice, limit_reached
from .db import session_scope
from .agent import ChessCoachAgent
from .analysis import ANALYSIS_VERSION
from .db_models import (
    AnalysisRow,
    PlayerMemoryRow,
    SyncJobRow,
)
from .llm import ask_coach, estimate_cost
from .importers import ImportSourceError, fetch_platform_pgn, preview_pgn_games
from .models import (
    AnalyzeResponse,
    CoachAnalysis,
    CoachAskRequest,
    CoachAskResponse,
    CoachFeedbackRequest,
    EvaluationPanel,
    PlayerProfile,
    ProgressSummary,
    QuizAttemptCreate,
    SyncGamesRequest,
    SyncJobView,
    TrainingSessionCreate,
    TrainingSessionView,
)
from .monitoring import log_event
from .repositories import (
    find_stored_game,
    get_or_create_player,
    load_analyses,
    player_profile,
    persist_analyses,
    progress_summary,
    training_session_view,
)
from .practice_agent import run_practice_agent
from .sync_queue import ACTIVE_STATUSES, notify_worker
from .time_trainer import TimeTrainerUnavailable, build_time_session
from .training import evaluate_attempt


router = APIRouter(prefix="/api")
coach_agent = ChessCoachAgent()


def _sync_failure_message(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        url = str(exc.request.url)
        status = exc.response.status_code
        if status == 403 and "chess.com" in url:
            return (
                "Chess.com returned 403 Forbidden. Add CHESSCOM_API_CONTACT to backend/.env "
                "(email or Chess.com username), use the lowercase handle, and retry. "
                "If you are on a cloud host (Render, etc.), Chess.com often blocks datacenter IPs — "
                "sync locally or use Lichess instead."
            )
        if status in {301, 308} and "chess.com" in url:
            return (
                "Chess.com redirected the username lookup. Enter the lowercase Chess.com handle "
                "(for example magnuscarlsen, not MagnusCarlsen)."
            )
        if status == 404 and "chess.com" in url:
            return "Chess.com could not find that username. Check spelling and capitalization."
        if status == 404 and "lichess.org" in url:
            return "Lichess could not find that username. Check spelling."
        return f"Game provider request failed ({status}) for {url}"
    return str(exc)


def _sync_job_view(row: SyncJobRow) -> SyncJobView:
    return SyncJobView(
        id=row.id,
        platform=row.platform,
        username=row.username,
        status=row.status,  # type: ignore[arg-type]
        total_games=row.total_games,
        analyzed_games=row.analyzed_games,
        skipped_games=row.skipped_games,
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _sync_error_message(exc: Exception) -> str:
    if isinstance(exc, ImportSourceError):
        return str(exc)
    return _sync_failure_message(exc) or exc.__class__.__name__


async def process_sync_job(job_id: str, request: SyncGamesRequest) -> None:
    """Run one claimed job. A retried job starts over: games it finished are found stored."""
    try:
        with session_scope() as session:
            job = session.get(SyncJobRow, job_id)
            if job is None:
                return
            job.status = "fetching"
            # Games a lost attempt analyzed come up as stored this time. They are already in
            # analyzed_games, so they must not count as skipped as well.
            already_counted = job.analyzed_games
            job.skipped_games = 0
        pgn = await fetch_platform_pgn(request.platform, request.username, request.max_games)
        previews = preview_pgn_games(
            pgn, request.username, request.platform, request.max_games
        )
        previews.sort(
            key=lambda game: (game.player_result == "loss", game.date), reverse=True
        )
        with session_scope() as session:
            job = session.get(SyncJobRow, job_id)
            if job is None:
                return
            job.status = "analyzing"
            job.total_games = len(previews)

        failed_games = 0
        for preview in previews:
            with session_scope() as session:
                job = session.get(SyncJobRow, job_id)
                if job is None:
                    return
                existing = find_stored_game(
                    session, job.player_id, preview.game_id, preview.link
                )
                # Games stored before start times were kept get one from any sync, no re-analysis.
                if existing is not None and existing.started_at is None:
                    existing.started_at = preview.started_at
                # Games re-analyzed offline lack the PGN-only fields (clocks, opponent rating,
                # termination), so a sync analyzes them once more from the fetched PGN.
                has_pgn_fields = existing is not None and "opponent_elo" in (
                    (existing.metadata_json or {}).get("game", {})
                )
                if existing and has_pgn_fields and ANALYSIS_VERSION in (
                    session.scalar(
                        select(AnalysisRow.retrieval_notes).where(
                            AnalysisRow.game_id == existing.id
                        )
                    )
                    or []
                ):
                    if already_counted:
                        already_counted -= 1
                    else:
                        job.skipped_games += 1
                    continue

            try:
                response = await asyncio.to_thread(
                    coach_agent.import_pgn_text,
                    preview.pgn,
                    request.username,
                    1,
                )
                with session_scope() as session:
                    persist_analyses(
                        session, request.platform, request.username, response
                    )
            except Exception as exc:
                # One unreadable game must not block every later game (and every later sync).
                failed_games += 1
                log_event(
                    "games_sync_game_failed",
                    {"job_id": job_id, "game_id": preview.game_id, "error": _sync_error_message(exc)},
                )
                response = None
            with session_scope() as session:
                job = session.get(SyncJobRow, job_id)
                if job:
                    if response is None:
                        job.skipped_games += 1
                    else:
                        job.analyzed_games += len(response.analyses)
                        job.skipped_games += 1 - len(response.analyses)

        with session_scope() as session:
            job = session.get(SyncJobRow, job_id)
            if job:
                job.status = "complete"
                if failed_games:
                    job.error = f"{failed_games} game(s) could not be analyzed and were skipped."
        log_event(
            "games_sync_completed",
            {"job_id": job_id, "platform": request.platform, "username": request.username},
        )
    except Exception as exc:
        message = _sync_error_message(exc)
        with session_scope() as session:
            job = session.get(SyncJobRow, job_id)
            if job:
                job.status = "failed"
                job.error = message
        log_event("games_sync_failed", {"job_id": job_id, "error": message})


@router.post("/games/sync", response_model=SyncJobView)
async def sync_games(request: SyncGamesRequest) -> SyncJobView:
    with session_scope() as session:
        player = get_or_create_player(session, request.platform, request.username)
        active = session.scalar(
            select(SyncJobRow)
            .where(SyncJobRow.player_id == player.id, SyncJobRow.status.in_(ACTIVE_STATUSES))
            .order_by(SyncJobRow.created_at.desc())
            .limit(1)
        )
        if active is not None:
            return _sync_job_view(active)
        job = SyncJobRow(
            player_id=player.id,
            platform=request.platform,
            username=request.username,
            max_games=request.max_games,
        )
        session.add(job)
        session.flush()
        view = _sync_job_view(job)
    notify_worker()
    return view


@router.get("/games/sync/{job_id}", response_model=SyncJobView)
def get_sync_job(job_id: str) -> SyncJobView:
    with session_scope() as session:
        job = session.get(SyncJobRow, job_id)
        if job is None:
            raise HTTPException(404, "Sync job not found")
        return _sync_job_view(job)


@router.get("/games/{platform}/{username}", response_model=AnalyzeResponse)
def get_analyzed_games(
    platform: str, username: str, game_id: str | None = None
) -> AnalyzeResponse:
    with session_scope() as session:
        return load_analyses(session, platform, username, game_id)


@router.get("/players/{platform}/{username}", response_model=PlayerProfile)
def get_player(platform: str, username: str, user_id: Viewer) -> PlayerProfile:
    with session_scope() as session:
        player = get_or_create_player(session, platform, username)
        profile = player_profile(session, player)
        if can_access(session, platform, username, user_id):
            return profile
        return public_profile(profile)


def _create_time_session(request: TrainingSessionCreate) -> TrainingSessionView:
    with session_scope() as session:
        try:
            plan = build_time_session(
                session, request.platform, request.username, request.position_count
            )
        except TimeTrainerUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        if plan is None:
            raise HTTPException(409, "No positions from your games fit the time trainer yet.")
        view = training_session_view(session, plan.id)
        if view is None:
            raise HTTPException(500, "Training session could not be created")
        log_event(
            "training_session_created",
            {
                "training_session_id": plan.id,
                "positions": len(view.positions),
                "puzzles": 0,
                "mode": request.mode,
                "difficulty": plan.difficulty,
            },
        )
        return view


@router.post("/training/sessions", response_model=TrainingSessionView)
async def create_training_session(
    request: TrainingSessionCreate, http_request: Request, user_id: Viewer
) -> TrainingSessionView:
    with session_scope() as session:
        require_access(session, request.platform, request.username, user_id)
    if request.mode == "time":
        # Stockfish vets every position, so keep it off the event loop. No LLM copy here:
        # the prompt has to stay neutral, and the verdict comes from the engine.
        return await asyncio.to_thread(_create_time_session, request)
    charge = QuotaCharge(http_request, user_id, "practice")
    try:
        with session_scope() as session:
            result = await run_practice_agent(
                session,
                request.platform,
                request.username,
                request.theme,
                request.position_count,
                request.moment_id,
                request.mode,
                take_llm_quota=charge.take,
            )
            view = training_session_view(session, result.plan.id)
            if view is None:
                raise HTTPException(500, "Training session could not be created")
            log_event(
                "training_session_created",
                {
                    "training_session_id": result.plan.id,
                    "positions": len(view.positions),
                    "puzzles": sum(item.source == "puzzle" for item in view.positions),
                    "mode": request.mode,
                    "difficulty": result.plan.difficulty,
                },
            )
            log_event(
                "practice_agent_completed",
                {
                    "training_session_id": result.plan.id,
                    "used_llm": result.used_llm,
                    "fallback": result.fallback,
                    "llm_limited": result.llm_limited,
                    "tools_used": result.tools_used,
                    "duration_ms": result.duration_ms,
                },
            )
    except Exception:
        await asyncio.to_thread(charge.refund)
        raise
    # After the session above has committed: with SQLite the refund would wait on its writes.
    if not result.used_llm:
        await asyncio.to_thread(charge.refund)
    if result.llm_limited:
        view.limit_notice = limit_notice(charge.scope)
    return view


@router.get("/training/sessions/{training_session_id}", response_model=TrainingSessionView)
def get_training_session(training_session_id: str, user_id: Viewer) -> TrainingSessionView:
    with session_scope() as session:
        view = training_session_view(session, training_session_id)
        if view is None:
            raise HTTPException(404, "Training session not found")
        require_player(session, view.player_id, user_id)
        return view


@router.post(
    "/training/sessions/{training_session_id}/attempts",
    response_model=EvaluationPanel,
)
def submit_training_attempt(
    training_session_id: str, request: QuizAttemptCreate, user_id: Viewer
) -> EvaluationPanel:
    with session_scope() as session:
        view = training_session_view(session, training_session_id)
        if view is None or request.position_id not in {item.id for item in view.positions}:
            raise HTTPException(404, "Training position not found in this session")
        require_player(session, view.player_id, user_id)
        try:
            result = evaluate_attempt(
                session,
                request.position_id,
                request.move,
                request.hints_used,
                request.elapsed_ms,
                request.timed_out,
            )
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        log_event(
            "quiz_attempted",
            {
                "training_session_id": training_session_id,
                "position_id": request.position_id,
                "correct": result.correct,
                "legal": result.legal,
                "hints_used": request.hints_used,
                "timed_out": bool(result.time_result and result.time_result.timed_out),
            },
        )
        return result


@router.get("/progress/{platform}/{username}", response_model=ProgressSummary)
def get_progress(platform: str, username: str, user_id: Viewer) -> ProgressSummary:
    with session_scope() as session:
        summary = progress_summary(session, platform, username)
        if can_access(session, platform, username, user_id):
            return summary
        return summary.model_copy(
            update={
                "player": public_profile(summary.player),
                "quiz_accuracy": {},
                "recent_attempts": 0,
                "transfer_score": None,
                "private": True,
            }
        )


def _player_memory_context(session, player_id: str) -> str:
    memory = session.get(PlayerMemoryRow, player_id)
    if memory is None:
        return ""
    themes = ", ".join(
        f"{theme.replace('_', ' ')} {weight:.2f}"
        for theme, weight in sorted(memory.recurring_themes.items(), key=lambda item: -item[1])[:5]
    )
    accuracy = ", ".join(f"{theme.replace('_', ' ')} {value:.0%}" for theme, value in memory.quiz_accuracy.items())
    return (
        f"Recurring weakness themes: {themes or 'not enough data'}\n"
        f"Quiz accuracy by theme: {accuracy or 'no attempts yet'}\n"
        f"Due positions: {memory.due_positions}; mastered positions: {memory.mastered_positions}"
    )


@router.post("/coach/ask", response_model=CoachAskResponse)
async def ask_coach_route(
    request: CoachAskRequest, http_request: Request, user_id: Viewer
) -> CoachAskResponse:
    def load_context() -> tuple[bool, str, CoachAnalysis | None]:
        with session_scope() as session:
            allowed = can_access(session, request.platform, request.username, user_id)
            memory = ""
            if allowed:
                player = get_or_create_player(session, request.platform, request.username)
                memory = _player_memory_context(session, player.id)
            if request.game_id is None:
                return allowed, memory, None
            analyses = load_analyses(session, request.platform, request.username, request.game_id).analyses
            return allowed, memory, analyses[0] if analyses else None

    charge = QuotaCharge(http_request, user_id, "coach")
    if not await asyncio.to_thread(charge.take):
        raise limit_reached(charge.scope)
    allowed, memory, analysis = await asyncio.to_thread(load_context)
    started = time.perf_counter()
    try:
        # Without access the coach still sees the public game, but gets no player identity,
        # so its tools cannot reach this player's practice data.
        response = await ask_coach(
            request.question,
            analysis,
            fen=request.fen,
            platform=request.platform if allowed else None,
            username=request.username if allowed else None,
            memory_context=memory,
            message_history=request.message_history,
        )
    except Exception:
        await asyncio.to_thread(charge.refund)
        raise
    log_event(
        "coach_answered",
        {
            "player": request.username,
            "game_id": request.game_id,
            "used_llm": response.used_llm,
            "fallback_reason": response.fallback_reason,
            "tools_used": response.tools_used,
            "arrows": len(response.arrows),
            "highlights": len(response.highlights),
            "annotations_dropped": response.annotations_dropped,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "usage": {
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "estimated_cost_usd": estimate_cost(response.input_tokens, response.output_tokens),
            },
        },
    )
    return response


@router.post("/coach/feedback")
def coach_feedback(request: CoachFeedbackRequest) -> dict[str, str]:
    log_event("coach_feedback", request.model_dump())
    return {"status": "recorded"}
