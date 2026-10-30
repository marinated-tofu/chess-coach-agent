"""Endgame trainer: play a position out against Stockfish and let the engine judge the result.

Drills come from two places:

* ``data/endgames/essentials.json``: hand-checked theory positions (tests validate each FEN).
* The player's own games: endgame moments where a stored engine eval shows a winning or drawn
  position slipping away, in a game that then finished worse than that.

A drill has a goal. "win" means convert: deliver mate, or (unless the drill's ``finish`` is
"mate") reach a decisive engine eval with a material edge the start did not have. "draw" means
hold: reach any draw, or still stand within the holding range when the move limit runs out.
Either goal fails early when the engine sees the result gone on two turns in a row, so one
noisy eval cannot end a drill.

Results are stored in the existing training tables, so they share the spaced-repetition
schedule: one TrainingPositionRow per player and FEN, a QuizAttemptRow per play-through, and
``schedule_review`` for the interval. No Lichess code or data is used here.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Protocol

import chess
from sqlalchemy import func, select
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
from .engine import MATE_CP, PositionEval, material_score
from .repositories import recompute_player_memory
from .training import schedule_review

ESSENTIALS_PATH = Path(__file__).resolve().parents[2] / "data" / "endgames" / "essentials.json"

Goal = Literal["win", "draw"]
Finish = Literal["engine", "mate"]
Status = Literal["playing", "passed", "failed"]

THEME = "endgame_conversion"  # the existing theme these drills train
PLAN_STATUS = "endgames"  # the one plan per player that owns their drill rows
SOURCE_ESSENTIAL = "essential"
SOURCE_GAME = "endgame"
GAME_DRILL_PREFIX = "game:"
GAME_DRILL_LIMIT = 24
CANDIDATE_MOMENT_LIMIT = 300

GAME_WIN_MOVE_LIMIT = 30
GAME_DRAW_MOVE_LIMIT = 20

# All scores are centipawns from the player's point of view.
WINNING_CP = 200  # at or above: winning. At or below minus this: lost. Between: drawn.
WIN_SLIPPED_CP = 75  # below this the win is gone
HOLD_LOST_CP = -350  # below this the draw is gone
DECISIVE_CP = 1000  # a conversion needs this much on the board...
CONVERT_MATERIAL_CP = 500  # ...and at least this material edge...
CONVERT_MATERIAL_GAIN_CP = 300  # ...and this much more than the drill started with
STRIKES_TO_FAIL = 2

ENGINE_DEPTH = 16
ENGINE_MAX_NODES = 300_000


@dataclass(frozen=True)
class Drill:
    id: str
    kind: Literal["essential", "game"]
    title: str
    category: str
    fen: str
    goal: Goal
    finish: Finish
    move_limit: int
    summary: str
    hint: str
    best_san: str = ""
    # Own-game context.
    moment_row_id: str | None = None
    game_id: str | None = None
    opponent: str | None = None
    played_at: str | None = None
    played_san: str | None = None
    move_number: int | None = None

    @property
    def player_color(self) -> chess.Color:
        return chess.Board(self.fen).turn


class Evaluator(Protocol):
    def evaluate(self, board: chess.Board, multipv: int = 2) -> PositionEval: ...


# --- essentials -------------------------------------------------------------------------------


@lru_cache(maxsize=1)
def load_essentials() -> tuple[Drill, ...]:
    if not ESSENTIALS_PATH.exists():
        return ()
    raw = json.loads(ESSENTIALS_PATH.read_text(encoding="utf-8"))
    return tuple(Drill(kind="essential", **item) for item in raw)


def get_essential(drill_id: str) -> Drill | None:
    return next((drill for drill in load_essentials() if drill.id == drill_id), None)


# --- own games --------------------------------------------------------------------------------


def _pov_cp(move: dict[str, Any], player_is_white: bool) -> int | None:
    """Stored eval after ``move`` (White's view) from the player's view, None without engine data."""
    mate, cp = move.get("eval_mate"), move.get("eval_cp")
    if mate is not None:
        white = mate > 0 or (mate == 0 and move.get("color") == "white")
        value = MATE_CP if white else -MATE_CP
    elif cp is not None:
        value = cp
    else:
        return None
    return value if player_is_white else -value


def _standing(cp: int) -> int:
    return 2 if cp >= WINNING_CP else 0 if cp <= -WINNING_CP else 1


RESULT_STANDING = {"win": 2, "draw": 1, "loss": 0}


def thrown_goal(moves: list[dict[str, Any]], ply: int, player_is_white: bool, player_result: str) -> Goal | None:
    """The goal for the position before the player's move at ``ply``, if this move gave it away.

    The position must have been winning or drawn, the move must have dropped it a step, and the
    game must have finished below where it stood.
    """
    by_ply = {move.get("ply"): move for move in moves}
    previous, played = by_ply.get(ply - 1), by_ply.get(ply)
    final = RESULT_STANDING.get(player_result)
    if previous is None or played is None or final is None:
        return None
    before, after = _pov_cp(previous, player_is_white), _pov_cp(played, player_is_white)
    if before is None or after is None:
        return None
    standing = _standing(before)
    if standing == 0 or _standing(after) >= standing or final >= standing:
        return None
    return "win" if standing == 2 else "draw"


def _game_drill(game: GameRow, moment: CriticalMomentRow) -> Drill | None:
    player_is_white = game.player_color == "white"
    goal = thrown_goal((game.metadata_json or {}).get("moves") or [], moment.ply, player_is_white, game.player_result)
    if goal is None:
        return None
    opponent = game.black if player_is_white else game.white
    outcome = "lost" if game.player_result == "loss" else "drew"
    best = f" The engine preferred {moment.best_san}." if moment.best_san else ""
    return Drill(
        id=f"{GAME_DRILL_PREFIX}{game.external_game_id}:{moment.ply}",
        kind="game",
        title=f"{'Convert' if goal == 'win' else 'Hold'} against {opponent}",
        category="Your games",
        fen=moment.fen_before,
        goal=goal,
        finish="engine",
        move_limit=GAME_WIN_MOVE_LIMIT if goal == "win" else GAME_DRAW_MOVE_LIMIT,
        summary=(
            f"You were {'winning' if goal == 'win' else 'holding the balance'} here, "
            f"played {moment.played_san} and {outcome} the game."
        ),
        hint=((moment.explanation or {}).get("better_plan") or "") + best,
        best_san=moment.best_san or "",
        moment_row_id=moment.id,
        game_id=game.external_game_id,
        opponent=opponent,
        played_at=game.played_at,
        played_san=moment.played_san,
        move_number=moment.move_number,
    )


def own_game_drills(session: Session, player: PlayerRow, limit: int = GAME_DRILL_LIMIT) -> list[Drill]:
    """Newest first, at most one per game (the earliest slip) and one per position."""
    moments = session.scalars(
        select(CriticalMomentRow)
        .join(GameRow, CriticalMomentRow.game_id == GameRow.id)
        .where(
            GameRow.player_id == player.id,
            GameRow.player_result.in_(("loss", "draw")),
            CriticalMomentRow.phase == "endgame",
        )
        .order_by(GameRow.played_at.desc(), CriticalMomentRow.ply)
        .limit(CANDIDATE_MOMENT_LIMIT)
    ).all()
    by_game: dict[str, list[CriticalMomentRow]] = defaultdict(list)
    for moment in moments:
        by_game[moment.game_id].append(moment)

    drills: list[Drill] = []
    seen: set[str] = set()
    for game_id, candidates in by_game.items():
        game = session.get(GameRow, game_id)
        if game is None:
            continue
        for moment in candidates:
            drill = _game_drill(game, moment)
            if drill is None:
                continue
            if drill.fen not in seen:
                seen.add(drill.fen)
                drills.append(drill)
            break
        if len(drills) >= limit:
            break
    return drills


def get_game_drill(session: Session, player: PlayerRow, drill_id: str) -> Drill | None:
    external_id, _, ply = drill_id.removeprefix(GAME_DRILL_PREFIX).rpartition(":")
    if not external_id or not ply.isdigit():
        return None
    game = session.scalar(
        select(GameRow).where(GameRow.player_id == player.id, GameRow.external_game_id == external_id)
    )
    if game is None:
        return None
    moment = session.scalar(
        select(CriticalMomentRow).where(CriticalMomentRow.game_id == game.id, CriticalMomentRow.ply == int(ply))
    )
    return _game_drill(game, moment) if moment else None


# --- judging ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Turn:
    status: Status
    reason: str = ""
    result: str = "playing"  # converted | held | won | lost_win | lost_draw | resigned
    fen: str = ""
    reply_san: str | None = None
    reply_uci: str | None = None
    strikes: int = 0


DRAW_REASONS = {
    chess.Termination.STALEMATE: "Stalemate.",
    chess.Termination.INSUFFICIENT_MATERIAL: "Insufficient material.",
    chess.Termination.THREEFOLD_REPETITION: "Draw by repetition.",
    chess.Termination.FIVEFOLD_REPETITION: "Draw by repetition.",
    chess.Termination.FIFTY_MOVES: "Fifty moves without a capture or pawn move.",
    chess.Termination.SEVENTYFIVE_MOVES: "Fifty moves without a capture or pawn move.",
}


def replay(drill: Drill, moves_uci: list[str]) -> chess.Board:
    """The drill's start plus ``moves_uci``. Raises ValueError on an illegal move."""
    board = chess.Board(drill.fen)
    for uci in moves_uci:
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            raise ValueError(f"Illegal move in the line: {uci}")
        board.push(move)
    return board


def _finished(drill: Drill, board: chess.Board) -> Turn | None:
    outcome = board.outcome(claim_draw=True)
    if outcome is None:
        return None
    fen = board.fen()
    if outcome.winner == drill.player_color:
        result = "converted" if drill.goal == "win" else "won"
        return Turn("passed", "Checkmate. You finished it.", result, fen)
    if outcome.winner is not None:
        return Turn("failed", "Checkmate. Stockfish punished the slip.", _lost(drill), fen)
    reason = DRAW_REASONS.get(outcome.termination, "Draw.")
    if drill.goal == "draw":
        return Turn("passed", f"{reason} You held the position.", "held", fen)
    return Turn("failed", f"{reason} The win got away.", _lost(drill), fen)


def _lost(drill: Drill) -> str:
    return "lost_win" if drill.goal == "win" else "lost_draw"


def _edge(board: chess.Board, color: chess.Color) -> int:
    return material_score(board, color)


def _converted(drill: Drill, board: chess.Board, score: int) -> bool:
    if drill.goal != "win" or drill.finish == "mate" or score < DECISIVE_CP:
        return False
    needed = max(CONVERT_MATERIAL_CP, _edge(chess.Board(drill.fen), drill.player_color) + CONVERT_MATERIAL_GAIN_CP)
    return _edge(board, drill.player_color) >= needed


def _at_move_limit(drill: Drill, score: int, fen: str) -> Turn:
    limit = f"{drill.move_limit} moves played."
    if drill.goal == "draw":
        if score >= -WINNING_CP:
            return Turn("passed", f"{limit} The engine says you held it.", "held", fen)
        return Turn("failed", f"{limit} The engine says the position is lost.", _lost(drill), fen)
    if drill.finish == "mate":
        return Turn("failed", f"{limit} No mate yet, so try a faster route.", _lost(drill), fen)
    if score >= WINNING_CP:
        return Turn("passed", f"{limit} The engine still has you winning.", "converted", fen)
    return Turn("failed", f"{limit} The engine no longer sees a win.", _lost(drill), fen)


def play_turn(drill: Drill, moves_uci: list[str], strikes: int, engine: Evaluator) -> Turn:
    """Judge the line after the player's latest move, then answer it with the engine's best reply.

    ``strikes`` comes back from the previous turn, so the server keeps no game state. The score
    is read after the player's move, which is the search that also picks the reply.
    """
    if len(moves_uci) % 2 == 0:
        raise ValueError("It is not the opponent's turn in this line.")
    board = replay(drill, moves_uci)
    finished = _finished(drill, board)
    if finished:
        return finished

    evaluation = engine.evaluate(board, multipv=1)
    score = evaluation.best.pov(drill.player_color)
    fen = board.fen()
    if _converted(drill, board, score):
        return Turn("passed", "The engine calls this decisive. Converted.", "converted", fen)
    if (len(moves_uci) + 1) // 2 >= drill.move_limit:
        return _at_move_limit(drill, score, fen)

    slipping = score < (WIN_SLIPPED_CP if drill.goal == "win" else HOLD_LOST_CP)
    strikes = strikes + 1 if slipping else 0
    if strikes >= STRIKES_TO_FAIL:
        reason = "The engine no longer sees a win." if drill.goal == "win" else "The engine says the draw is gone."
        return Turn("failed", reason, _lost(drill), fen, strikes=strikes)

    move = evaluation.best.move
    if move is None:
        raise RuntimeError("The engine did not return a move.")
    san = board.san(move)
    board.push(move)
    finished = _finished(drill, board)
    if finished:
        return Turn(finished.status, finished.reason, finished.result, finished.fen, san, move.uci(), strikes)
    return Turn("playing", fen=board.fen(), reply_san=san, reply_uci=move.uci(), strikes=strikes)


# --- recording --------------------------------------------------------------------------------


def _plan(session: Session, player_id: str) -> TrainingPlanRow:
    plan = session.scalar(
        select(TrainingPlanRow).where(TrainingPlanRow.player_id == player_id, TrainingPlanRow.status == PLAN_STATUS)
    )
    if plan is None:
        plan = TrainingPlanRow(player_id=player_id, status=PLAN_STATUS, focus_themes=[THEME])
        session.add(plan)
        session.flush()
    return plan


def _position(session: Session, player_id: str, drill: Drill) -> TrainingPositionRow:
    """The player's one row for this FEN. Keyed by FEN because re-analysis replaces moment rows."""
    plan = _plan(session, player_id)
    source = SOURCE_ESSENTIAL if drill.kind == "essential" else SOURCE_GAME
    position = session.scalar(
        select(TrainingPositionRow).where(
            TrainingPositionRow.plan_id == plan.id,
            TrainingPositionRow.source == source,
            TrainingPositionRow.fen == drill.fen,
        )
    )
    if position is None:
        order = session.scalar(
            select(func.count(TrainingPositionRow.id)).where(TrainingPositionRow.plan_id == plan.id)
        )
        position = TrainingPositionRow(
            plan_id=plan.id,
            moment_id=drill.moment_row_id,
            position_order=(order or 0) + 1,
            fen=drill.fen,
            correct_move=drill.best_san,
            choices=[],
            theme=THEME,
            difficulty="intermediate",
            explanation=drill.summary,
            source=source,
            prompt=drill.title,
            hint=drill.hint,
        )
        session.add(position)
        session.flush()
    return position


def record_result(
    session: Session, player: PlayerRow, drill: Drill, turn: Turn, hints_used: int, elapsed_ms: int
) -> ReviewScheduleRow:
    position = _position(session, player.id, drill)
    passed = turn.status == "passed"
    session.add(
        QuizAttemptRow(
            player_id=player.id,
            position_id=position.id,
            submitted_move=turn.result,
            correct=passed,
            legal=True,
            hints_used=hints_used,
            elapsed_ms=elapsed_ms,
        )
    )
    schedule = schedule_review(session, player.id, position.id, passed, hints_used)
    recompute_player_memory(session, player.id)
    return schedule


@dataclass(frozen=True)
class DrillProgress:
    attempts: int = 0
    passes: int = 0
    last_passed: bool | None = None
    due_at: datetime | None = None
    interval_days: int | None = None


def drill_progress(session: Session, player: PlayerRow) -> dict[str, DrillProgress]:
    """FEN -> stored progress for every drill this player has played."""
    rows = session.execute(
        select(TrainingPositionRow.id, TrainingPositionRow.fen, ReviewScheduleRow.due_at, ReviewScheduleRow.interval_days)
        .join(TrainingPlanRow, TrainingPositionRow.plan_id == TrainingPlanRow.id)
        .join(ReviewScheduleRow, ReviewScheduleRow.position_id == TrainingPositionRow.id, isouter=True)
        .where(TrainingPlanRow.player_id == player.id, TrainingPlanRow.status == PLAN_STATUS)
    ).all()
    progress: dict[str, DrillProgress] = {}
    for position_id, fen, due_at, interval in rows:
        attempts = session.scalars(
            select(QuizAttemptRow.correct)
            .where(QuizAttemptRow.position_id == position_id)
            .order_by(QuizAttemptRow.created_at)
        ).all()
        progress[fen] = DrillProgress(
            attempts=len(attempts),
            passes=sum(attempts),
            last_passed=attempts[-1] if attempts else None,
            due_at=due_at if due_at is None or due_at.tzinfo else due_at.replace(tzinfo=UTC),
            interval_days=interval,
        )
    return progress
