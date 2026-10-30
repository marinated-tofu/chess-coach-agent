from __future__ import annotations

import random
from collections import Counter
from datetime import UTC, datetime, timedelta

import chess
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db_models import (
    LIBRARY_PLAN_STATUS,
    CriticalMomentRow,
    GameRow,
    PlayerRow,
    QuizAttemptRow,
    ReviewScheduleRow,
    TrainingPlanRow,
    TrainingPositionRow,
)
from .classification import winning_chances
from .engine import EngineAnalyzer
from .models import EvaluationPanel, QuizPanel
from .puzzles import Puzzle, normalize_theme, select_puzzles
from .repositories import get_or_create_player, recompute_player_memory, training_session_view
from .time_trainer import ran_out_of_time, timed_result


def difficulty_for(session: Session, player: PlayerRow, theme: str) -> str:
    attempts = session.scalars(
        select(QuizAttemptRow)
        .join(TrainingPositionRow, QuizAttemptRow.position_id == TrainingPositionRow.id)
        .where(QuizAttemptRow.player_id == player.id, TrainingPositionRow.theme == theme)
    ).all()
    if len(attempts) >= 3:
        accuracy = sum(item.correct for item in attempts[-10:]) / min(len(attempts), 10)
        if accuracy < 0.4:
            return "beginner"
        if accuracy > 0.8:
            return "advanced"
        return "intermediate"
    rating = player.current_rating or 1400
    return "beginner" if rating < 1200 else "advanced" if rating > 1800 else "intermediate"


def _move_choices(fen: str, correct_move: str, difficulty: str) -> list[str]:
    if difficulty == "advanced":
        return []
    board = chess.Board(fen)
    # Forcing moves make believable distractors; the order is shuffled per position so the
    # answer is never in a fixed slot but stays stable across reloads.
    candidates = sorted(
        (move for move in board.legal_moves if board.san(move) != correct_move),
        key=lambda move: (not board.gives_check(move), not board.is_capture(move)),
    )
    count = 3 if difficulty == "beginner" else 4
    choices = [correct_move, *(board.san(move) for move in candidates[: count - 1])]
    random.Random(fen).shuffle(choices)
    return choices


# TrainingPlanRow.status of a session of due reviews, so the study plan can tell them apart.
REVIEW_PLAN_STATUS = "review"
PUZZLE_RATING_OFFSET = {"beginner": -150, "intermediate": 0, "advanced": 150}


def top_weakness(session: Session, player: PlayerRow) -> str | None:
    """The player's most frequent critical-moment theme, if any."""
    themes = Counter(
        session.scalars(
            select(CriticalMomentRow.theme)
            .join(GameRow, CriticalMomentRow.game_id == GameRow.id)
            .where(GameRow.player_id == player.id)
        ).all()
    )
    return themes.most_common(1)[0][0] if themes else None


def _seen_puzzle_ids(session: Session, player: PlayerRow) -> set[str]:
    return set(
        session.scalars(
            select(TrainingPositionRow.puzzle_id)
            .join(TrainingPlanRow, TrainingPositionRow.plan_id == TrainingPlanRow.id)
            .where(
                TrainingPlanRow.player_id == player.id,
                TrainingPositionRow.puzzle_id.is_not(None),
            )
        ).all()
    )


def _pick_puzzles(
    session: Session, player: PlayerRow, theme: str | None, difficulty: str, count: int
) -> list[Puzzle]:
    rating = (player.current_rating or 1400) + PUZZLE_RATING_OFFSET.get(difficulty, 0)
    return select_puzzles(theme, rating, count, exclude_ids=_seen_puzzle_ids(session, player))


def _puzzle_explanation(puzzle: Puzzle) -> str:
    return (
        f"Lichess puzzle {puzzle.id} (rated {puzzle.rating}) for "
        f"{puzzle.theme.replace('_', ' ')}. The solution starts with {puzzle.solution_san}."
    )
def default_quiz_copy(position: TrainingPositionRow) -> tuple[str, str | None]:
    theme_label = position.theme.replace("_", " ")
    if position.source == "puzzle":
        prompt = f"Lichess puzzle on {theme_label}: find the best move."
    else:
        prompt = f"You had a {theme_label} pattern in your game — what would you play?"
    hint = None
    if position.difficulty == "beginner":
        hint = (
            f"Start with checks and captures, then inspect loose pieces. "
            f"Theme: {theme_label}."
        )
    return prompt, hint


def apply_default_quiz_copy(session: Session, plan_id: str) -> None:
    positions = session.scalars(
        select(TrainingPositionRow)
        .where(TrainingPositionRow.plan_id == plan_id)
        .order_by(TrainingPositionRow.position_order)
    ).all()
    for position in positions:
        if not position.prompt or position.prompt == "What would you play in this position?":
            prompt, hint = default_quiz_copy(position)
            position.prompt = prompt
            position.hint = hint
    session.flush()


def build_training_session(
    session: Session,
    platform: str,
    username: str,
    theme: str | None = None,
    position_count: int = 5,
    moment_id: str | None = None,
    mode: str = "mixed",
    ordered_moment_ids: list[str] | None = None,
) -> TrainingPlanRow:
    """Build a practice session.

    Positions from the player's own games always come first. In "mixed" mode, if there are
    fewer than ``position_count`` of them, the session is topped up with library puzzles for
    the requested theme or the player's top weakness. In "puzzles" mode the session holds
    only puzzles. A session for one specific ``moment_id`` is never topped up.
    """
    player = get_or_create_player(session, platform, username)
    if mode == "puzzles":
        return _build_puzzle_session(session, player, theme, position_count)
    moment_query = (
        select(CriticalMomentRow)
        .join(GameRow, CriticalMomentRow.game_id == GameRow.id)
        .where(GameRow.player_id == player.id, CriticalMomentRow.best_san.is_not(None))
        .order_by(CriticalMomentRow.severity.desc())
    )
    if moment_id:
        moment_query = moment_query.where(
            CriticalMomentRow.external_moment_id == moment_id
        )
    elif theme:
        moment_query = moment_query.where(CriticalMomentRow.theme == theme)
    candidates = session.scalars(moment_query).all()
    trainable = [
        item for item in candidates if (item.explanation or {}).get("trainable", False)
    ]
    moments = (trainable or candidates)[:position_count]
    if ordered_moment_ids:
        by_id = {item.id: item for item in (trainable or candidates)}
        ranked = [by_id[item_id] for item_id in ordered_moment_ids if item_id in by_id]
        if ranked:
            moments = ranked[:position_count]
    if not moments and (theme or moment_id):
        candidates = session.scalars(
            select(CriticalMomentRow)
            .join(GameRow, CriticalMomentRow.game_id == GameRow.id)
            .where(GameRow.player_id == player.id, CriticalMomentRow.best_san.is_not(None))
            .order_by(CriticalMomentRow.severity.desc())
        ).all()
        trainable = [
            item for item in candidates if (item.explanation or {}).get("trainable", False)
        ]
        moments = (trainable or candidates)[:position_count]
    selected_theme = (
        theme
        or (moments[0].theme if moments else None)
        or top_weakness(session, player)
        or "candidate_move_discipline"
    )
    difficulty = difficulty_for(session, player, selected_theme)
    shortfall = 0 if moment_id else position_count - len(moments)
    puzzles = _pick_puzzles(session, player, selected_theme, difficulty, shortfall)
    focus = list(dict.fromkeys([item.theme for item in moments] + [item.theme for item in puzzles]))
    plan = TrainingPlanRow(
        player_id=player.id,
        focus_themes=focus or [selected_theme],
        difficulty=difficulty,
    )
    session.add(plan)
    session.flush()
    for index, moment in enumerate(moments, start=1):
        correct = moment.best_san or ""
        position = TrainingPositionRow(
            plan_id=plan.id,
            moment_id=moment.id,
            position_order=index,
            fen=moment.fen_before,
            correct_move=correct,
            choices=_move_choices(moment.fen_before, correct, difficulty),
            theme=moment.theme,
            difficulty=difficulty,
            explanation=(moment.explanation or {}).get("what_happened", ""),
            source="game",
        )
        prompt, hint = default_quiz_copy(position)
        position.prompt = prompt
        position.hint = hint
        session.add(position)
    _add_puzzle_positions(session, plan, puzzles, difficulty, start=len(moments) + 1)
    session.flush()
    return plan


def build_due_session(
    session: Session, platform: str, username: str, position_count: int = 5
) -> TrainingPlanRow | None:
    """A session of the positions whose review is due, oldest first. None if nothing is due.

    Each position is copied into the new session and its review schedule moves with it, so
    answering updates that schedule. Ordinary sessions build new rows and leave it due forever.
    """
    player = get_or_create_player(session, platform, username)
    due = session.execute(
        select(ReviewScheduleRow, TrainingPositionRow)
        .join(TrainingPositionRow, TrainingPositionRow.id == ReviewScheduleRow.position_id)
        .join(TrainingPlanRow, TrainingPlanRow.id == TrainingPositionRow.plan_id)
        .where(
            ReviewScheduleRow.player_id == player.id,
            ReviewScheduleRow.due_at <= datetime.now(UTC),
            # Library puzzles aren't re-served, and endgames are played out on /endgames.
            TrainingPlanRow.status != LIBRARY_PLAN_STATUS,
            TrainingPositionRow.source.not_like("endgame%"),
        )
        .order_by(ReviewScheduleRow.due_at)
    ).all()
    picked: dict[str, tuple[ReviewScheduleRow, TrainingPositionRow]] = {}
    for schedule, position in due:
        # Repeat sessions store the same moment twice; show each board once per session.
        picked.setdefault(position.fen, (schedule, position))
        if len(picked) == position_count:
            break
    if not picked:
        return None
    positions = [position for _schedule, position in picked.values()]
    plan = TrainingPlanRow(
        player_id=player.id,
        status=REVIEW_PLAN_STATUS,
        focus_themes=list(dict.fromkeys(item.theme for item in positions)),
        difficulty=positions[0].difficulty,
    )
    session.add(plan)
    session.flush()
    for order, (schedule, old) in enumerate(picked.values(), start=1):
        copy = TrainingPositionRow(
            plan_id=plan.id,
            moment_id=old.moment_id,
            position_order=order,
            fen=old.fen,
            correct_move=old.correct_move,
            choices=old.choices,
            theme=old.theme,
            difficulty=old.difficulty,
            explanation=old.explanation,
            source=old.source,
            puzzle_id=old.puzzle_id,
            rating=old.rating,
            solution=old.solution,
            prompt=old.prompt,
            hint=old.hint,
        )
        session.add(copy)
        session.flush()
        schedule.position_id = copy.id
    session.flush()
    return plan


def _build_puzzle_session(
    session: Session, player: PlayerRow, theme: str | None, position_count: int
) -> TrainingPlanRow:
    selected_theme = normalize_theme(theme) or normalize_theme(top_weakness(session, player))
    difficulty = difficulty_for(session, player, selected_theme or "missed_tactic")
    puzzles = _pick_puzzles(session, player, selected_theme, difficulty, position_count)
    plan = TrainingPlanRow(
        player_id=player.id,
        focus_themes=list(dict.fromkeys(item.theme for item in puzzles))
        or [selected_theme or "missed_tactic"],
        difficulty=difficulty,
    )
    session.add(plan)
    session.flush()
    _add_puzzle_positions(session, plan, puzzles, difficulty, start=1)
    session.flush()
    return plan


def _add_puzzle_positions(
    session: Session, plan: TrainingPlanRow, puzzles: list[Puzzle], difficulty: str, start: int
) -> None:
    for index, puzzle in enumerate(puzzles, start=start):
        session.add(
            TrainingPositionRow(
                plan_id=plan.id,
                moment_id=None,
                position_order=index,
                fen=puzzle.fen,
                correct_move=puzzle.solution_san,
                choices=_move_choices(puzzle.fen, puzzle.solution_san, difficulty),
                theme=puzzle.theme,
                difficulty=difficulty,
                explanation=_puzzle_explanation(puzzle),
                source="puzzle",
                puzzle_id=puzzle.id,
                rating=puzzle.rating,
                solution=list(puzzle.solution),
            )
        )


def quiz_panel(session: Session, plan_id: str, position_id: str | None = None) -> QuizPanel | None:
    plan_view = training_session_view(session, plan_id)
    if not plan_view or not plan_view.positions:
        return None
    position = next((item for item in plan_view.positions if item.id == position_id), plan_view.positions[0])
    row = session.get(TrainingPositionRow, position.id)
    hint = row.hint if row else None
    question = row.prompt if row and row.prompt else "What would you play in this position?"
    if hint is None and row and position.difficulty == "beginner":
        hint = f"Start with checks and captures. The engine move begins with {row.correct_move[:1]}."
    return QuizPanel(
        training_session_id=plan_id,
        position_id=position.id,
        fen=position.fen,
        question=question,
        choices=position.choices,
        theme=position.theme,
        difficulty=position.difficulty,
        hint=hint,
    )


def _parse_move(board: chess.Board, submitted: str) -> chess.Move | None:
    try:
        return board.parse_san(submitted)
    except ValueError:
        try:
            move = chess.Move.from_uci(submitted)
            return move if move in board.legal_moves else None
        except ValueError:
            return None


def schedule_review(
    session: Session, player_id: str, position_id: str, correct: bool, hints_used: int = 0
) -> ReviewScheduleRow:
    """Move a position's review date: 1 day after a miss, 3 after a hint, else 7 doubling to 30."""
    schedule = session.scalar(
        select(ReviewScheduleRow).where(ReviewScheduleRow.position_id == position_id)
    )
    now = datetime.now(UTC)
    if schedule is None:
        schedule = ReviewScheduleRow(
            player_id=player_id,
            position_id=position_id,
            due_at=now,
            interval_days=1,
            consecutive_successes=0,
        )
        session.add(schedule)
    if not correct:
        schedule.interval_days = 1
        schedule.consecutive_successes = 0
    elif hints_used:
        schedule.interval_days = 3
        schedule.consecutive_successes += 1
    else:
        schedule.consecutive_successes += 1
        schedule.interval_days = min(30, 7 * (2 ** max(0, schedule.consecutive_successes - 1)))
    schedule.due_at = now + timedelta(days=schedule.interval_days)
    session.flush()
    return schedule


def evaluate_attempt(
    session: Session,
    position_id: str,
    submitted_move: str,
    hints_used: int = 0,
    elapsed_ms: int = 0,
    timed_out: bool = False,
) -> EvaluationPanel:
    position = session.get(TrainingPositionRow, position_id)
    if position is None:
        raise ValueError("Training position not found")
    plan = session.get(TrainingPlanRow, position.plan_id)
    if plan is None:
        raise ValueError("Training plan not found")
    timing = position.timing
    timed_out = bool(timing) and ran_out_of_time(timing, timed_out, elapsed_ms)
    board = chess.Board(position.fen)
    move = None if timed_out else _parse_move(board, submitted_move.strip())
    legal = timed_out or move is not None
    cp_loss = None
    correct = False
    is_best = False
    win_chance_loss = None
    if move:
        submitted_san = board.san(move)
        is_best = correct = submitted_san == position.correct_move
        analyzer = EngineAnalyzer()
        pov = board.turn
        try:
            before = analyzer.analyse(board, pov)
            board.push(move)
            after = analyzer.analyse(board, pov)
        finally:
            analyzer.close()
        engine_backed = before.engine_backed and after.engine_backed
        if before.score_cp is not None and after.score_cp is not None and (engine_backed or not timing):
            # Mate scores are +/-100000; clamp like the classifier so a mating miss reads
            # as a 10-pawn loss, not 1000.
            before_cp = max(-1000, min(1000, before.score_cp))
            after_cp = max(-1000, min(1000, after.score_cp))
            cp_loss = round(max(0, before_cp - after_cp) / 100, 2)
            # A heuristic eval is too rough to accept a move the answer key rejects.
            correct = correct or (engine_backed and cp_loss <= 0.5)
            win_chance_loss = max(
                0.0, winning_chances(before.score_cp) - winning_chances(after.score_cp)
            )
            if timing and is_best:
                # The two searches can disagree by a pawn at this depth; the engine's own
                # move loses nothing by definition.
                cp_loss, win_chance_loss = 0.0, 0.0

    time_result = None
    if timing and legal:
        time_result = timed_result(timing, elapsed_ms, timed_out, is_best, win_chance_loss)
        if time_result.verdict != "unavailable":
            # Same scale the game review labels moves on, so verdict and outcome agree.
            correct = time_result.verdict in ("best", "good")

    schedule = _record_attempt(
        session, position, plan.player_id, submitted_move, correct, legal, cp_loss, hints_used, elapsed_ms
    )

    explanation = (
        f"{submitted_move} is a strong engine-approved candidate. {position.explanation}"
        if correct
        else f"The stronger move is {position.correct_move}. {position.explanation}"
    )
    if timed_out:
        explanation = f"Time ran out. The stronger move is {position.correct_move}. {position.explanation}"
    if not legal:
        explanation = "That move is not legal in this position. Check the board and try again."
    return EvaluationPanel(
        position_id=position.id,
        fen=position.fen,
        submitted_move=submitted_move,
        best_move=position.correct_move,
        legal=legal,
        correct=correct,
        cp_loss=cp_loss,
        explanation=explanation,
        next_review_at=schedule.due_at,
        time_result=time_result,
    )


def _record_attempt(
    session: Session,
    position: TrainingPositionRow,
    player_id: str,
    submitted_move: str,
    correct: bool,
    legal: bool,
    cp_loss: float | None,
    hints_used: int,
    elapsed_ms: int,
) -> ReviewScheduleRow:
    """Store an attempt, move the position's review schedule and refresh player memory."""
    session.add(
        QuizAttemptRow(
            player_id=player_id,
            position_id=position.id,
            submitted_move=submitted_move,
            correct=correct,
            legal=legal,
            cp_loss=cp_loss,
            hints_used=hints_used,
            elapsed_ms=elapsed_ms,
        )
    )
    schedule = schedule_review(session, player_id, position.id, correct, hints_used)
    recompute_player_memory(session, player_id)
    return schedule


def record_puzzle_attempt(
    session: Session,
    player: PlayerRow,
    puzzle: Puzzle,
    submitted_move: str,
    correct: bool,
    elapsed_ms: int = 0,
) -> ReviewScheduleRow:
    """Count a puzzle solved on the puzzle page through the same tables as a practice attempt.

    The line was already graded against the puzzle's solution, so no engine is involved.
    """
    plan = session.scalar(
        select(TrainingPlanRow)
        .where(TrainingPlanRow.player_id == player.id, TrainingPlanRow.status == LIBRARY_PLAN_STATUS)
        .limit(1)
    )
    if plan is None:
        plan = TrainingPlanRow(player_id=player.id, status=LIBRARY_PLAN_STATUS, focus_themes=[])
        session.add(plan)
        session.flush()
    position_query = select(TrainingPositionRow).where(
        TrainingPositionRow.plan_id == plan.id, TrainingPositionRow.puzzle_id == puzzle.id
    )
    position = session.scalar(position_query)
    if position is None:
        order = session.scalar(
            select(func.count())
            .select_from(TrainingPositionRow)
            .where(TrainingPositionRow.plan_id == plan.id)
        )
        difficulty = difficulty_for(session, player, puzzle.theme)
        _add_puzzle_positions(session, plan, [puzzle], difficulty, start=(order or 0) + 1)
        session.flush()
        position = session.scalar(position_query)
    return _record_attempt(
        session, position, player.id, submitted_move, correct, True, None, 0, elapsed_ms
    )
