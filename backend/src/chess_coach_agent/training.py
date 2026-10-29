from __future__ import annotations

import random
from collections import Counter
from datetime import UTC, datetime, timedelta

import chess
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db_models import (
    CriticalMomentRow,
    GameRow,
    PlayerRow,
    QuizAttemptRow,
    ReviewScheduleRow,
    TrainingPlanRow,
    TrainingPositionRow,
)
from .engine import EngineAnalyzer
from .models import EvaluationPanel, QuizPanel
from .puzzles import Puzzle, normalize_theme, select_puzzles
from .repositories import get_or_create_player, recompute_player_memory, training_session_view


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


def evaluate_attempt(
    session: Session,
    position_id: str,
    submitted_move: str,
    hints_used: int = 0,
    elapsed_ms: int = 0,
) -> EvaluationPanel:
    position = session.get(TrainingPositionRow, position_id)
    if position is None:
        raise ValueError("Training position not found")
    plan = session.get(TrainingPlanRow, position.plan_id)
    if plan is None:
        raise ValueError("Training plan not found")
    board = chess.Board(position.fen)
    move = _parse_move(board, submitted_move.strip())
    legal = move is not None
    cp_loss = None
    correct = False
    if move:
        submitted_san = board.san(move)
        correct = submitted_san == position.correct_move
        analyzer = EngineAnalyzer()
        pov = board.turn
        try:
            before = analyzer.analyse(board, pov)
            board.push(move)
            after = analyzer.analyse(board, pov)
        finally:
            analyzer.close()
        if before.score_cp is not None and after.score_cp is not None:
            # Mate scores are +/-100000; clamp like the classifier so a mating miss reads
            # as a 10-pawn loss, not 1000.
            before_cp = max(-1000, min(1000, before.score_cp))
            after_cp = max(-1000, min(1000, after.score_cp))
            cp_loss = round(max(0, before_cp - after_cp) / 100, 2)
            correct = correct or cp_loss <= 0.5

    attempt = QuizAttemptRow(
        player_id=plan.player_id,
        position_id=position.id,
        submitted_move=submitted_move,
        correct=correct,
        legal=legal,
        cp_loss=cp_loss,
        hints_used=hints_used,
        elapsed_ms=elapsed_ms,
    )
    session.add(attempt)

    schedule = session.scalar(
        select(ReviewScheduleRow).where(ReviewScheduleRow.position_id == position.id)
    )
    now = datetime.now(UTC)
    if schedule is None:
        schedule = ReviewScheduleRow(
            player_id=plan.player_id,
            position_id=position.id,
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
    recompute_player_memory(session, plan.player_id)

    explanation = (
        f"{submitted_move} is a strong engine-approved candidate. {position.explanation}"
        if correct
        else f"The stronger move is {position.correct_move}. {position.explanation}"
    )
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
    )
