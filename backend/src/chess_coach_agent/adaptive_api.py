from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException
from sqlalchemy import select

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
from .training import build_training_session, evaluate_attempt


router = APIRouter(prefix="/api")
coach_agent = ChessCoachAgent()
ACTIVE_SYNC_STATUSES = ("queued", "fetching", "analyzing")
# A job whose row has not moved in this long lost its worker (e.g. the server restarted).
STALE_SYNC_AFTER = timedelta(minutes=10)


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
    return str(exc) or exc.__class__.__name__


async def _process_sync_job(job_id: str, request: SyncGamesRequest) -> None:
    try:
        with session_scope() as session:
            job = session.get(SyncJobRow, job_id)
            if job is None:
                return
            job.status = "fetching"
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


def _is_stale(job: SyncJobRow) -> bool:
    updated = job.updated_at if job.updated_at.tzinfo else job.updated_at.replace(tzinfo=UTC)
    return datetime.now(UTC) - updated > STALE_SYNC_AFTER


@router.post("/games/sync", response_model=SyncJobView)
async def sync_games(
    request: SyncGamesRequest, background_tasks: BackgroundTasks
) -> SyncJobView:
    with session_scope() as session:
        player = get_or_create_player(session, request.platform, request.username)
        active_jobs = session.scalars(
            select(SyncJobRow)
            .where(
                SyncJobRow.player_id == player.id,
                SyncJobRow.status.in_(ACTIVE_SYNC_STATUSES),
            )
            .order_by(SyncJobRow.created_at.desc())
        ).all()
        for active in active_jobs:
            if not _is_stale(active):
                return _sync_job_view(active)
            active.status = "failed"
            active.error = "Sync was interrupted before it finished. Start it again to resume."
        job = SyncJobRow(
            player_id=player.id,
            platform=request.platform,
            username=request.username,
        )
        session.add(job)
        session.flush()
        view = _sync_job_view(job)
    background_tasks.add_task(_process_sync_job, job.id, request)
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
def get_player(platform: str, username: str) -> PlayerProfile:
    with session_scope() as session:
        player = get_or_create_player(session, platform, username)
        return player_profile(session, player)


@router.post("/training/sessions", response_model=TrainingSessionView)
def create_training_session(request: TrainingSessionCreate) -> TrainingSessionView:
    with session_scope() as session:
        plan = build_training_session(
            session,
            request.platform,
            request.username,
            request.theme,
            request.position_count,
            request.moment_id,
            request.mode,
        )
        view = training_session_view(session, plan.id)
        if view is None:
            raise HTTPException(500, "Training session could not be created")
        log_event(
            "training_session_created",
            {
                "training_session_id": plan.id,
                "positions": len(view.positions),
                "puzzles": sum(item.source == "puzzle" for item in view.positions),
                "mode": request.mode,
                "difficulty": plan.difficulty,
            },
        )
        return view


@router.get("/training/sessions/{training_session_id}", response_model=TrainingSessionView)
def get_training_session(training_session_id: str) -> TrainingSessionView:
    with session_scope() as session:
        view = training_session_view(session, training_session_id)
        if view is None:
            raise HTTPException(404, "Training session not found")
        return view


@router.post(
    "/training/sessions/{training_session_id}/attempts",
    response_model=EvaluationPanel,
)
def submit_training_attempt(
    training_session_id: str, request: QuizAttemptCreate
) -> EvaluationPanel:
    with session_scope() as session:
        view = training_session_view(session, training_session_id)
        if view is None or request.position_id not in {item.id for item in view.positions}:
            raise HTTPException(404, "Training position not found in this session")
        try:
            result = evaluate_attempt(
                session,
                request.position_id,
                request.move,
                request.hints_used,
                request.elapsed_ms,
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
            },
        )
        return result


@router.get("/progress/{platform}/{username}", response_model=ProgressSummary)
def get_progress(platform: str, username: str) -> ProgressSummary:
    with session_scope() as session:
        return progress_summary(session, platform, username)


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
async def ask_coach_route(request: CoachAskRequest) -> CoachAskResponse:
    def load_context() -> tuple[str, CoachAnalysis | None]:
        with session_scope() as session:
            player = get_or_create_player(session, request.platform, request.username)
            memory = _player_memory_context(session, player.id)
            if request.game_id is None:
                return memory, None
            analyses = load_analyses(session, request.platform, request.username, request.game_id).analyses
            return memory, analyses[0] if analyses else None

    memory, analysis = await asyncio.to_thread(load_context)
    started = time.perf_counter()
    response = await ask_coach(
        request.question,
        analysis,
        fen=request.fen,
        platform=request.platform,
        username=request.username,
        memory_context=memory,
        message_history=request.message_history,
    )
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
