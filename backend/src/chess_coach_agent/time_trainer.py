"""Time trainer: practice positions where the player spent their clock badly.

Two kinds of position come out of the stored per-move clock data:

* ``rushed``: the player moved faster than usual, was not short of time, and the move cost
  at least a mistake's worth of winning chances.
* ``burned``: the player thought far longer than usual in a position where Stockfish rates
  the top two moves about equal, so there was little to find.

The stored move data only nominates candidates. Each one is then checked with a fresh
Stockfish search, and that search supplies the best move, the cost of the played move and
the countdown. Without Stockfish no session is built: the heuristic fallback in
``EngineAnalyzer`` is fine for a rough review but not for telling a player what was critical.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from statistics import median
from typing import Any, Literal

import chess
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .classification import MISTAKE_LOSS, classify_win_chance_loss, winning_chances
from .db_models import GameRow, PlayerRow, TrainingPlanRow, TrainingPositionRow
from .engine import EngineAnalyzer, stockfish_path
from .models import TimeTrainerResult
from .pgn import parse_time_control
from .repositories import get_or_create_player

TIME_THEME = "time_management"
TIME_PROMPT = "Find the best move before the clock runs out."

# Recent games scanned for candidates; move JSON is heavy, and old habits matter less.
SCAN_GAMES = 300
# A game needs this many timed non-book moves for its median to mean anything.
MIN_TIMED_MOVES = 8

RUSHED_MAX_SHARE = 0.75  # of the game's typical move time
RUSHED_MIN_LOSS = MISTAKE_LOSS  # winning chances, same scale as classification.py
BURNED_MIN_SHARE = 3.0
BURNED_MIN_SECONDS = 15.0
BURNED_MAX_WIN_PCT_LOSS = 5.0  # the long think must not have ended in a real error
# Top two moves within about 2 Win% points: nothing in the position needed a long think.
SIMPLE_MAX_GAP = 0.04

# Countdowns start from a cold board, without the game's context, hence the floors.
CRITICAL_MIN_SECONDS = 15
CRITICAL_MAX_SECONDS = 90
CRITICAL_MAX_BASE_SHARE = 0.10
SIMPLE_MIN_SECONDS = 8
SIMPLE_MAX_SECONDS = 20

# Network and rendering slack before a late submission counts as a flag.
LATE_GRACE_MS = 1500
# Stockfish checks per requested position; many nominated positions do not survive.
ENGINE_CHECKS_PER_POSITION = 6

Kind = Literal["rushed", "burned"]


class TimeTrainerUnavailable(RuntimeError):
    """Raised when Stockfish cannot be used, since the trainer needs real evaluations."""


class TimeTrainerStatus(BaseModel):
    platform: str
    username: str
    status: Literal["ready", "no_clock_data", "no_candidates"]
    clock_games: int = 0
    rushed_count: int = 0
    burned_count: int = 0


@dataclass(frozen=True)
class TimeCandidate:
    kind: Kind
    fen: str
    played_san: str
    played_uci: str
    spent_seconds: float
    typical_seconds: float
    base_seconds: int
    stored_win_pct_loss: float
    move_number: int
    opponent: str
    played_at: str


def position_key(fen: str) -> str:
    """Pieces, side, castling and en passant: the same position reached on any move number."""
    return " ".join(fen.split()[:4])


def countdown_seconds(
    kind: Kind, typical_seconds: float, base_seconds: int, win_chance_loss: float = 0.0
) -> int:
    """What the position deserves, scaled to the player's own pace in that game.

    A critical position earns two to four typical moves, more the more it cost, capped at
    a tenth of the base clock. A simple one earns one typical move.
    """
    if kind == "burned":
        return round(min(SIMPLE_MAX_SECONDS, max(SIMPLE_MIN_SECONDS, typical_seconds)))
    ceiling = max(
        CRITICAL_MIN_SECONDS, min(CRITICAL_MAX_SECONDS, base_seconds * CRITICAL_MAX_BASE_SHARE)
    )
    wanted = typical_seconds * (2 + 2 * min(win_chance_loss, 1.0))
    return round(min(ceiling, max(CRITICAL_MIN_SECONDS, wanted)))


def candidates_from_moves(
    moves: list[dict[str, Any]],
    color: str,
    time_control: str,
    opponent: str = "",
    played_at: str = "",
) -> list[TimeCandidate] | None:
    """Nominate positions from one game's stored moves; None when it has no usable clock data."""
    clock_setup = parse_time_control(time_control)
    if clock_setup is None:
        return None
    own = [
        move
        for move in moves
        if move.get("color") == color
        and move.get("time_spent_seconds") is not None
        and move.get("classification") != "book"
    ]
    if len(own) < MIN_TIMED_MOVES:
        return None
    typical = float(median(move["time_spent_seconds"] for move in own))
    found: list[TimeCandidate] = []
    for move in own:
        loss = move.get("win_pct_loss")
        if loss is None or not move.get("best_san") or not move.get("fen_before"):
            continue
        spent = float(move["time_spent_seconds"])
        # Fast moves under time trouble were forced by the clock, not a choice to rush.
        rushed = (
            not move.get("time_pressure")
            and spent <= typical * RUSHED_MAX_SHARE
            and loss >= RUSHED_MIN_LOSS * 50
        )
        burned = (
            spent >= max(typical * BURNED_MIN_SHARE, BURNED_MIN_SECONDS)
            and loss < BURNED_MAX_WIN_PCT_LOSS
        )
        if not rushed and not burned:
            continue
        found.append(
            TimeCandidate(
                kind="rushed" if rushed else "burned",
                fen=move["fen_before"],
                played_san=move["san"],
                played_uci=move["uci"],
                spent_seconds=spent,
                typical_seconds=typical,
                base_seconds=clock_setup[0],
                stored_win_pct_loss=float(loss),
                move_number=int(move.get("move_number") or 0),
                opponent=opponent,
                played_at=played_at,
            )
        )
    return found


def _scan_games(session: Session, player: PlayerRow) -> tuple[int, list[TimeCandidate]]:
    rows = session.execute(
        select(
            GameRow.metadata_json,
            GameRow.player_color,
            GameRow.time_control,
            GameRow.white,
            GameRow.black,
            GameRow.played_at,
        )
        .where(GameRow.player_id == player.id, GameRow.time_control != "")
        .order_by(GameRow.played_at.desc())
        .limit(SCAN_GAMES)
    ).all()
    clock_games = 0
    candidates: list[TimeCandidate] = []
    for stored, color, time_control, white, black, played_at in rows:
        found = candidates_from_moves(
            (stored or {}).get("moves") or [],
            color,
            time_control,
            opponent=black if color == "white" else white,
            played_at=played_at,
        )
        if found is None:
            continue
        clock_games += 1
        candidates.extend(found)
    return clock_games, candidates


def time_trainer_status(
    session: Session, platform: str, username: str, player: PlayerRow | None
) -> TimeTrainerStatus:
    if player is None:
        return TimeTrainerStatus(platform=platform, username=username, status="no_clock_data")
    clock_games, candidates = _scan_games(session, player)
    rushed = sum(item.kind == "rushed" for item in candidates)
    status: Literal["ready", "no_clock_data", "no_candidates"] = "ready"
    if not clock_games:
        status = "no_clock_data"
    elif not candidates:
        status = "no_candidates"
    return TimeTrainerStatus(
        platform=platform,
        username=player.username,
        status=status,
        clock_games=clock_games,
        rushed_count=rushed,
        burned_count=len(candidates) - rushed,
    )


def _seen_positions(session: Session, player: PlayerRow) -> set[str]:
    fens = session.scalars(
        select(TrainingPositionRow.fen)
        .join(TrainingPlanRow, TrainingPositionRow.plan_id == TrainingPlanRow.id)
        .where(TrainingPlanRow.player_id == player.id, TrainingPositionRow.theme == TIME_THEME)
    ).all()
    return {position_key(fen) for fen in fens}


def _queue(candidates: list[TimeCandidate], seen: set[str]) -> list[TimeCandidate]:
    """Worst first, one entry per position, unseen positions ahead of repeats, kinds alternating."""
    unique: dict[str, TimeCandidate] = {}
    for item in sorted(
        candidates,
        key=lambda c: c.stored_win_pct_loss if c.kind == "rushed" else c.spent_seconds,
        reverse=True,
    ):
        unique.setdefault(position_key(item.fen), item)
    ordered = sorted(unique.values(), key=lambda c: position_key(c.fen) in seen)
    rushed = [item for item in ordered if item.kind == "rushed"]
    burned = [item for item in ordered if item.kind == "burned"]
    mixed: list[TimeCandidate] = []
    while rushed or burned:
        if rushed:
            mixed.append(rushed.pop(0))
        if burned:
            mixed.append(burned.pop(0))
    return mixed


def _engine_timing(
    analyzer: EngineAnalyzer, item: TimeCandidate
) -> tuple[dict[str, Any], str, str] | None:
    """Confirm a candidate with Stockfish. Returns (timing, best_san, explanation) or None."""
    board = chess.Board(item.fen)
    mover = board.turn
    view = analyzer.evaluate(board, multipv=2)
    best = view.best.move
    if view.heuristic or best is None or best not in board.legal_moves:
        return None
    best_san = board.san(best)
    best_chances = winning_chances(view.best.pov(mover))
    played = chess.Move.from_uci(item.played_uci)
    if played not in board.legal_moves:
        return None
    after = board.copy(stack=False)
    after.push(played)
    after_view = analyzer.evaluate(after, multipv=1)
    if after_view.heuristic:
        return None
    played_loss = max(0.0, best_chances - winning_chances(after_view.best.pov(mover)))

    if item.kind == "rushed":
        if played_loss < RUSHED_MIN_LOSS:
            return None
        explanation = (
            f"You played {item.played_san} in {item.spent_seconds:.1f}s, well under your usual "
            f"{item.typical_seconds:.1f}s. Stockfish says it gave up "
            f"{played_loss * 50:.1f} Win% points."
        )
    else:
        if view.second is None:
            return None
        gap = best_chances - winning_chances(view.second.pov(mover))
        if gap > SIMPLE_MAX_GAP:
            return None
        explanation = (
            f"You spent {item.spent_seconds:.1f}s on {item.played_san}, against your usual "
            f"{item.typical_seconds:.1f}s. Stockfish rates its top two moves within "
            f"{gap * 50:.1f} Win% points, so a quick sound move was enough here."
        )
    budget = countdown_seconds(
        item.kind, item.typical_seconds, item.base_seconds, played_loss
    )
    timing = {
        "kind": item.kind,
        "budget_seconds": budget,
        "original_seconds": item.spent_seconds,
        "typical_seconds": item.typical_seconds,
        "played_san": item.played_san,
        "played_verdict": _verdict(played_loss, played.uci() == best.uci()),
        "played_win_pct_loss": round(played_loss * 50, 2),
        "move_number": item.move_number,
        "opponent": item.opponent,
        "played_at": item.played_at,
    }
    return timing, best_san, explanation


def build_time_session(
    session: Session,
    platform: str,
    username: str,
    position_count: int = 5,
    analyzer: EngineAnalyzer | None = None,
) -> TrainingPlanRow | None:
    """Build a timed session from the player's games; None when no position survives."""
    if analyzer is None and not stockfish_path():
        raise TimeTrainerUnavailable("The time trainer needs Stockfish, which is not installed.")
    player = get_or_create_player(session, platform, username)
    _, candidates = _scan_games(session, player)
    queue = _queue(candidates, _seen_positions(session, player))
    engine = analyzer or EngineAnalyzer()
    chosen: list[tuple[dict[str, Any], str, str, str]] = []
    try:
        for item in queue[: position_count * ENGINE_CHECKS_PER_POSITION]:
            checked = _engine_timing(engine, item)
            if checked is not None:
                chosen.append((*checked, item.fen))
            if len(chosen) == position_count:
                break
    finally:
        if analyzer is None:
            engine.close()
    if not chosen:
        return None
    # Countdown length and order would otherwise hint at which positions are critical.
    random.shuffle(chosen)
    plan = TrainingPlanRow(
        player_id=player.id, focus_themes=[TIME_THEME], difficulty="intermediate"
    )
    session.add(plan)
    session.flush()
    for index, (timing, best_san, explanation, fen) in enumerate(chosen, start=1):
        session.add(
            TrainingPositionRow(
                plan_id=plan.id,
                position_order=index,
                fen=fen,
                correct_move=best_san,
                # Multiple choice would hand over the answer the clock is testing.
                choices=[],
                theme=TIME_THEME,
                difficulty="intermediate",
                explanation=explanation,
                source="game",
                prompt=TIME_PROMPT,
                timing=timing,
            )
        )
    session.flush()
    return plan


def _verdict(win_chance_loss: float, is_best: bool) -> str:
    # "best" names exactly the move Stockfish picked, which the verdict shows next to it.
    return "best" if is_best else classify_win_chance_loss(win_chance_loss) or "good"


def ran_out_of_time(timing: dict[str, Any], flagged: bool, elapsed_ms: int) -> bool:
    return flagged or elapsed_ms > timing["budget_seconds"] * 1000 + LATE_GRACE_MS


def timed_result(
    timing: dict[str, Any],
    elapsed_ms: int,
    timed_out: bool,
    is_best: bool,
    win_chance_loss: float | None,
) -> TimeTrainerResult:
    """Compare this attempt with the original move; ``win_chance_loss`` None means no engine."""
    if timed_out:
        verdict = "timed_out"
    elif win_chance_loss is None:
        verdict = "unavailable"
    else:
        verdict = _verdict(win_chance_loss, is_best)
    return TimeTrainerResult(
        kind=timing["kind"],
        budget_seconds=timing["budget_seconds"],
        original_seconds=timing["original_seconds"],
        typical_seconds=timing["typical_seconds"],
        played_san=timing["played_san"],
        played_verdict=timing["played_verdict"],
        played_win_pct_loss=timing["played_win_pct_loss"],
        attempt_seconds=round(elapsed_ms / 1000, 1),
        timed_out=timed_out,
        verdict=verdict,  # type: ignore[arg-type]
        win_pct_loss=None if win_chance_loss is None else round(win_chance_loss * 50, 2),
        move_number=timing["move_number"],
        opponent=timing["opponent"],
        played_at=timing["played_at"],
    )
