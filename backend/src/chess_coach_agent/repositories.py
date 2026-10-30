from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .db_models import (
    LIBRARY_PLAN_STATUS,
    AnalysisRow,
    CriticalMomentRow,
    GameRow,
    PlayerMemoryRow,
    PlayerRow,
    QuizAttemptRow,
    ReviewScheduleRow,
    TrainingPlanRow,
    TrainingPositionRow,
)
from .models import (
    AnalyzeResponse,
    CoachAnalysis,
    CriticalMoment,
    GameMetadata,
    MoveRecord,
    PlayerProfile,
    ProgressSummary,
    TrainingPositionView,
    TrainingSessionView,
)


def normalize_username(username: str) -> str:
    return username.strip().lower()


def get_or_create_player(session: Session, platform: str, username: str) -> PlayerRow:
    normalized = normalize_username(username)
    row = session.scalar(
        select(PlayerRow).where(
            PlayerRow.platform == platform,
            PlayerRow.username_normalized == normalized,
        )
    )
    if row:
        return row
    row = PlayerRow(platform=platform, username=username.strip(), username_normalized=normalized)
    session.add(row)
    session.flush()
    session.add(PlayerMemoryRow(player_id=row.id))
    return row


def player_profile(session: Session, player: PlayerRow) -> PlayerProfile:
    memory = session.get(PlayerMemoryRow, player.id)
    return PlayerProfile(
        id=player.id,
        platform=player.platform,  # type: ignore[arg-type]
        username=player.username,
        current_rating=player.current_rating,
        recurring_themes=memory.recurring_themes if memory else {},
        quiz_accuracy=memory.quiz_accuracy if memory else {},
        mastered_positions=memory.mastered_positions if memory else 0,
        due_positions=memory.due_positions if memory else 0,
    )


def game_url(link: str) -> str | None:
    """Return the link when it identifies one game (a Chess.com/Lichess game URL)."""
    parsed = urlparse(link.strip())
    if parsed.scheme in {"http", "https"} and parsed.path.strip("/"):
        return link.strip()
    return None


def find_stored_game(
    session: Session, player_id: str, game_id: str, link: str
) -> GameRow | None:
    """Find a player's stored game by id, falling back to its game URL.

    Game ids hash the PGN headers, so a game whose opponent later renamed their
    account gets a new id on the next sync; the URL still identifies it.
    """
    game = session.scalar(
        select(GameRow).where(
            GameRow.player_id == player_id,
            GameRow.external_game_id == game_id,
        )
    )
    url = game_url(link)
    if game is None and url:
        game = session.scalar(
            select(GameRow)
            .where(GameRow.player_id == player_id, GameRow.link == url)
            .order_by(GameRow.created_at)
            .limit(1)
        )
    return game


def persist_analyses(
    session: Session,
    platform: str,
    username: str,
    response: AnalyzeResponse,
) -> PlayerRow:
    player = get_or_create_player(session, platform, username)
    latest_rating = player.current_rating
    for analysis in response.analyses:
        metadata = analysis.game
        game = find_stored_game(session, player.id, metadata.game_id, metadata.link)
        if game is None:
            game = GameRow(player_id=player.id, external_game_id=metadata.game_id)
            session.add(game)
        game.external_game_id = metadata.game_id
        game.white = metadata.white
        game.black = metadata.black
        game.result = metadata.result
        game.player_result = metadata.player_result
        game.player_color = metadata.player_color
        game.player_elo = metadata.player_elo
        game.played_at = metadata.date
        # Offline re-analysis rebuilds metadata from old JSON, so never clear a stored time.
        game.started_at = metadata.started_at or game.started_at
        game.time_control = metadata.time_control
        game.link = metadata.link
        game.metadata_json = {
            "game": metadata.model_dump(mode="json"),
            "moves": [move.model_dump(mode="json") for move in analysis.moves],
        }
        session.flush()

        analysis_row = session.scalar(select(AnalysisRow).where(AnalysisRow.game_id == game.id))
        if analysis_row is None:
            analysis_row = AnalysisRow(game_id=game.id, summary=analysis.summary)
            session.add(analysis_row)
        analysis_row.summary = analysis.summary
        analysis_row.training_plan = analysis.training_plan
        analysis_row.retrieval_notes = analysis.retrieval_notes

        session.execute(delete(CriticalMomentRow).where(CriticalMomentRow.game_id == game.id))
        for moment in analysis.moments:
            session.add(
                CriticalMomentRow(
                    game_id=game.id,
                    external_moment_id=moment.id,
                    move_number=moment.move_number,
                    ply=moment.ply,
                    phase=moment.phase,
                    theme=moment.theme,
                    played_san=moment.played_san,
                    best_san=moment.best_san,
                    fen_before=moment.fen_before,
                    fen_after=moment.fen_after,
                    eval_swing=moment.eval_swing,
                    severity=moment.severity,
                    explanation={
                        "judgment": moment.judgment,
                        "win_probability_loss": moment.win_probability_loss,
                        "move_accuracy": moment.move_accuracy,
                        "trainable": moment.trainable,
                        "summary": moment.summary,
                        "what_happened": moment.what_happened,
                        "better_plan": moment.better_plan,
                        "principle": moment.principle,
                        "drill_prompt": moment.drill_prompt,
                    },
                )
            )
        if metadata.player_elo is not None:
            latest_rating = metadata.player_elo
    player.current_rating = latest_rating
    session.flush()
    recompute_player_memory(session, player.id)
    return player


def load_analyses(
    session: Session, platform: str, username: str, game_id: str | None = None
) -> AnalyzeResponse:
    player = session.scalar(
        select(PlayerRow).where(
            PlayerRow.platform == platform,
            PlayerRow.username_normalized == normalize_username(username),
        )
    )
    if player is None:
        return AnalyzeResponse(analyses=[])
    query = select(GameRow).where(GameRow.player_id == player.id)
    if game_id is not None:
        query = query.where(GameRow.external_game_id == game_id)
    games = session.scalars(
        query.order_by(GameRow.played_at.desc(), GameRow.created_at.desc())
    ).all()
    analyses: list[CoachAnalysis] = []
    for game in games:
        analysis = session.scalar(select(AnalysisRow).where(AnalysisRow.game_id == game.id))
        if analysis is None:
            continue
        stored = game.metadata_json or {}
        game_payload = stored.get("game", stored)
        moves_payload = stored.get("moves", [])
        metadata = GameMetadata(
            game_id=game.external_game_id,
            source=game_payload.get("source", platform),
            white=game.white,
            black=game.black,
            result=game.result,
            date=game.played_at,
            started_at=game.started_at,
            link=game.link,
            eco=game_payload.get("eco", ""),
            time_control=game.time_control,
            player_color=game.player_color,
            player_result=game.player_result,
            player_elo=game.player_elo,
            opponent_elo=game_payload.get("opponent_elo"),
            termination=game_payload.get("termination", ""),
        )
        moments = session.scalars(
            select(CriticalMomentRow)
            .where(CriticalMomentRow.game_id == game.id)
            .order_by(CriticalMomentRow.ply)
        ).all()
        analyses.append(
            CoachAnalysis(
                game=metadata,
                moves=[MoveRecord.model_validate(item) for item in moves_payload],
                moments=[
                    CriticalMoment(
                        id=item.external_moment_id,
                        game_id=game.external_game_id,
                        ply=item.ply,
                        move_number=item.move_number,
                        phase=item.phase,  # type: ignore[arg-type]
                        theme=item.theme,
                        played_san=item.played_san,
                        best_san=item.best_san,
                        fen_before=item.fen_before,
                        fen_after=item.fen_after,
                        eval_swing=item.eval_swing,
                        severity=item.severity,
                        judgment=(item.explanation or {}).get("judgment", "inaccuracy"),
                        win_probability_loss=(item.explanation or {}).get(
                            "win_probability_loss", item.severity
                        ),
                        move_accuracy=(item.explanation or {}).get("move_accuracy", 0),
                        trainable=(item.explanation or {}).get("trainable", False),
                        summary=(item.explanation or {}).get("summary", ""),
                        what_happened=(item.explanation or {}).get("what_happened", ""),
                        better_plan=(item.explanation or {}).get("better_plan", ""),
                        principle=(item.explanation or {}).get("principle", item.theme),
                        drill_prompt=(item.explanation or {}).get("drill_prompt", ""),
                    )
                    for item in moments
                ],
                summary=analysis.summary,
                training_plan=analysis.training_plan,
                retrieval_notes=analysis.retrieval_notes,
            )
        )
    return AnalyzeResponse(analyses=analyses)


def recompute_player_memory(session: Session, player_id: str) -> PlayerMemoryRow:
    memory = session.get(PlayerMemoryRow, player_id)
    if memory is None:
        memory = PlayerMemoryRow(player_id=player_id)
        session.add(memory)
    themes = Counter(
        session.scalars(
            select(CriticalMomentRow.theme)
            .join(GameRow, CriticalMomentRow.game_id == GameRow.id)
            .where(GameRow.player_id == player_id)
        ).all()
    )
    total = sum(themes.values()) or 1
    memory.recurring_themes = {name: round(count / total, 3) for name, count in themes.items()}

    attempts = session.scalars(select(QuizAttemptRow).where(QuizAttemptRow.player_id == player_id)).all()
    by_theme: dict[str, list[bool]] = {}
    for attempt in attempts:
        position = session.get(TrainingPositionRow, attempt.position_id)
        # Library puzzles and essential endgames train the theme but do not measure transfer
        # from the player's games.
        if position and position.source not in ("puzzle", "essential"):
            by_theme.setdefault(position.theme, []).append(attempt.correct)
    memory.quiz_accuracy = {
        theme: round(sum(values) / len(values), 3) for theme, values in by_theme.items()
    }
    now = datetime.now(UTC)
    schedules = session.execute(
        select(ReviewScheduleRow, TrainingPlanRow.status)
        .join(TrainingPositionRow, TrainingPositionRow.id == ReviewScheduleRow.position_id)
        .join(TrainingPlanRow, TrainingPlanRow.id == TrainingPositionRow.plan_id)
        .where(ReviewScheduleRow.player_id == player_id)
    ).all()
    memory.due_positions = sum(
        _aware(item.due_at) <= now and status != LIBRARY_PLAN_STATUS for item, status in schedules
    )
    memory.mastered_positions = sum(item.consecutive_successes >= 3 for item, _ in schedules)
    session.flush()
    return memory


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def training_session_view(session: Session, plan_id: str) -> TrainingSessionView | None:
    plan = session.get(TrainingPlanRow, plan_id)
    if plan is None:
        return None
    positions = session.scalars(
        select(TrainingPositionRow)
        .where(TrainingPositionRow.plan_id == plan.id)
        .order_by(TrainingPositionRow.position_order)
    ).all()
    return TrainingSessionView(
        id=plan.id,
        player_id=plan.player_id,
        focus_themes=plan.focus_themes,
        difficulty=plan.difficulty,  # type: ignore[arg-type]
        status=plan.status,
        positions=[
            TrainingPositionView(
                id=item.id,
                order=item.position_order,
                fen=item.fen,
                choices=item.choices,
                theme=item.theme,
                difficulty=item.difficulty,  # type: ignore[arg-type]
                source="puzzle" if item.source == "puzzle" else "game",
                rating=item.rating,
                time_budget_seconds=(item.timing or {}).get("budget_seconds"),
                prompt=item.prompt or "What would you play in this position?",
                hint=item.hint,
            )
            for item in positions
        ],
    )


def progress_summary(session: Session, platform: str, username: str) -> ProgressSummary:
    player = get_or_create_player(session, platform, username)
    recompute_player_memory(session, player.id)
    games = session.scalars(
        select(GameRow).where(GameRow.player_id == player.id).order_by(GameRow.played_at)
    ).all()
    record = Counter(game.player_result for game in games)
    themes = Counter(
        session.scalars(
            select(CriticalMomentRow.theme)
            .join(GameRow, CriticalMomentRow.game_id == GameRow.id)
            .where(GameRow.player_id == player.id)
        ).all()
    )
    attempts = session.scalars(select(QuizAttemptRow).where(QuizAttemptRow.player_id == player.id)).all()
    profile = player_profile(session, player)
    game_accuracy = 1 - (sum(themes.values()) / max(len(games) * 4, 1))
    quiz_average = sum(profile.quiz_accuracy.values()) / len(profile.quiz_accuracy) if profile.quiz_accuracy else None
    transfer = round((max(game_accuracy, 0) + quiz_average) / 2, 3) if quiz_average is not None else None
    return ProgressSummary(
        player=profile,
        total_games=len(games),
        record=dict(record),
        rating_history=[
            {"date": game.played_at, "rating": game.player_elo, "result": game.player_result}
            for game in games
            if game.player_elo is not None
        ],
        theme_frequency=dict(themes),
        quiz_accuracy=profile.quiz_accuracy,
        recent_attempts=len(attempts),
        transfer_score=transfer,
    )
