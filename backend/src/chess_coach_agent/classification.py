"""Per-move labels, move accuracy and game accuracy from a full-game engine eval series.

Everything here works on Lichess "winning chances" (``wc``), a number in [-1, 1] from the
mover's point of view, computed from centipawns clamped to +/-1000:

    wc(cp)   = 2 / (1 + exp(-0.00368208 * cp)) - 1
    Win%     = 50 + 50 * wc            (so 0.10 wc = 5 Win% points)
    loss     = max(0, wc_before - wc_after)   for the side that moved

Mates count as +/-1000 cp here, so Win% runs from 2.5 to 97.5 (as on Lichess); use the mate
fields to tell a mate from a big advantage. The UI shows ``loss`` in Win% points (``MoveRecord.win_pct_loss = loss * 50``). For reference,
Chess.com's "expected points" are Win% / 100, so 0.10 wc = 0.05 expected points.

Move labels
-----------
Labels are checked in this order; the first that applies wins.

========== ===================================================================================
Label      Rule
========== ===================================================================================
book       ``loss < 0.10`` and the move is at or before the deepest ply of the game whose
           position is a named line in the lichess-org/chess-openings table (``openings.py``,
           searched up to ply 50, so transpositions count). Without that table: the first
           ``FALLBACK_BOOK_PLIES`` (8) plies while every move so far has ``loss < 0.04``.
           An engine-significant error is never hidden behind Book.
miss       The opponent's previous move lost ``>= 0.20`` (a mistake or blunder), this move
           loses ``>= 0.10`` of it back, and the mover is still no worse off than before the
           opponent's error. If the mover ends up worse than that, it is a plain error instead.
blunder    ``loss >= 0.30``  (15 Win% points)
mistake    ``loss >= 0.20``  (10 Win% points)
inaccuracy ``loss >= 0.10``  (5 Win% points)
brilliant  Near-best (``loss < 0.04``) and a real sacrifice: after the move the opponent can
           win at least ``SACRIFICE_MIN_CP`` (200 cp, i.e. more than a pawn) of material by a
           legal capture followed by a static exchange, net of anything the move itself
           captured. Not obvious: the mover was below 0.90 wc (95 Win%) before the move,
           is at least 40 Win% after it, and the move is not checkmate.
great      Best-class move (see below) where the second-best engine line (MultiPV 2) is at
           least 0.20 wc worse for the mover *and* lands in a different outcome bucket
           (winning > 0.40 wc, losing < -0.40 wc, otherwise drawish). Plain recaptures on the
           square the opponent just captured on and checkmating moves (labeled best) are
           excluded.
best       The engine's top move, or ``loss < 0.01`` (half a Win% point, below depth-9
           noise). A move Stockfish itself picked is never labeled an error, matching
           ``docs/moment_selection.md``.
excellent  ``loss < 0.04``  (2 Win% points)
good       ``loss < 0.10``
========== ===================================================================================

The inaccuracy / mistake / blunder boundaries are the Lichess ``Advice.scala`` thresholds that
critical-moment selection already used, so ``docs/moment_selection.md`` stays true.

Accuracy
--------
Per move (Lichess ``AccuracyPercent.fromWinPercents``)::

    accuracy = clamp(103.1668100711649 * exp(-0.04354415386753951 * win_pct_loss)
                     - 3.166924740191411 + 1, 0, 100)

Per game and side (Lichess ``AccuracyPercent.gameAccuracy``): build the White Win% series
``[Win%(15 cp), Win% after ply 1, ..., Win% after ply N]`` (Lichess starts from a fixed 15 cp
initial eval). Window size ``w = clamp(N // 10, 2, 8)``; each move gets a volatility weight
``clamp(stdev(window), 0.5, 12)`` where the windows are ``w - 2`` copies of the first window
followed by every sliding window of ``w`` points (population standard deviation). For each side,

    accuracy = (weighted_mean(move accuracies, weights) + harmonic_mean(move accuracies)) / 2

where the harmonic mean floors each value at 1 so one zero-accuracy move cannot zero it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import chess

from .engine import PIECE_VALUES

MoveClassification = Literal[
    "brilliant",
    "great",
    "best",
    "excellent",
    "good",
    "book",
    "inaccuracy",
    "mistake",
    "miss",
    "blunder",
]

INACCURACY_LOSS = 0.10
MISTAKE_LOSS = 0.20
BLUNDER_LOSS = 0.30
BEST_LOSS = 0.01
EXCELLENT_LOSS = 0.04
GREAT_GAP = 0.20
OUTCOME_BUCKET_WC = 0.40
BRILLIANT_MAX_WC_BEFORE = 0.90
BRILLIANT_MIN_WC_AFTER = -0.20
SACRIFICE_MIN_CP = 200
FALLBACK_BOOK_PLIES = 8
LICHESS_INITIAL_CP = 15

_SEE_KING_VALUE = 20000


def winning_chances(score_cp: int) -> float:
    """Map a player-POV engine score to Lichess-style winning chances [-1, 1]."""
    cp = max(-1000, min(1000, score_cp))
    return 2 / (1 + math.exp(-0.00368208 * cp)) - 1


def win_percent(score_cp: int) -> float:
    """Lichess Win% (0-100) for a centipawn score from one side's point of view."""
    return 50 + 50 * winning_chances(score_cp)


def classify_win_chance_loss(loss: float) -> str | None:
    if loss >= BLUNDER_LOSS:
        return "blunder"
    if loss >= MISTAKE_LOSS:
        return "mistake"
    if loss >= INACCURACY_LOSS:
        return "inaccuracy"
    return None


def move_accuracy(win_probability_loss: float) -> float:
    """Lichess move accuracy from a winning-chance loss (wc units, not Win% points)."""
    win_percent_loss = max(0.0, win_probability_loss * 50)
    raw = 103.1668100711649 * math.exp(-0.04354415386753951 * win_percent_loss)
    return max(0.0, min(100.0, raw - 3.166924740191411 + 1))


def _stdev(values: Sequence[float]) -> float:
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def game_accuracy(
    white_win_pcts: Sequence[float], white_moves_first: bool = True
) -> dict[str, float | None]:
    """Lichess game accuracy per side from White's Win% after each ply (see module docs)."""
    series = [win_percent(LICHESS_INITIAL_CP), *white_win_pcts]
    if len(series) < 2:
        return {"white": None, "black": None}
    window = max(2, min(8, len(white_win_pcts) // 10))
    head = [series[:window]] * (min(window, len(series)) - 2)
    windows = head + [series[i : i + window] for i in range(len(series) - window + 1)]
    weights = [max(0.5, min(12.0, _stdev(w))) for w in windows]

    scored: dict[str, list[tuple[float, float]]] = {"white": [], "black": []}
    for index, (prev, nxt) in enumerate(zip(series, series[1:])):
        white_moved = (index % 2 == 0) == white_moves_first
        loss = (prev - nxt) if white_moved else (nxt - prev)
        accuracy = move_accuracy(max(0.0, loss) / 50)
        scored["white" if white_moved else "black"].append((accuracy, weights[index]))

    result: dict[str, float | None] = {}
    for side, pairs in scored.items():
        if not pairs:
            result[side] = None
            continue
        weighted = sum(a * w for a, w in pairs) / sum(w for _, w in pairs)
        harmonic = len(pairs) / sum(1 / max(1.0, a) for a, _ in pairs)
        result[side] = round((weighted + harmonic) / 2, 1)
    return result


def _see_value(piece: chess.Piece) -> int:
    return _SEE_KING_VALUE if piece.piece_type == chess.KING else PIECE_VALUES[piece.piece_type]


def _exchange_gain(board: chess.Board, square: chess.Square, side: bool) -> int:
    """Material ``side`` wins by capturing first on ``square`` (static exchange, 0 if it
    should not capture). Recaptures always use the least valuable attacker; pins are ignored."""
    target = board.piece_at(square)
    attackers = board.attackers(side, square)
    if target is None or not attackers:
        return 0
    from_square = min(attackers, key=lambda sq: _see_value(board.piece_at(sq)))  # type: ignore[arg-type]
    attacker = board.piece_at(from_square)
    assert attacker is not None
    after = board.copy(stack=False)
    after.remove_piece_at(from_square)
    after.set_piece_at(square, attacker)
    return max(0, _see_value(target) - _exchange_gain(after, square, not side))


def material_exposed(board: chess.Board, color: bool) -> int:
    """Most material the side to move can win from ``color`` with one legal capture plus
    the static exchange that follows. ``board.turn`` must be the opponent of ``color``."""
    best = 0
    for move in board.legal_moves:
        victim = board.piece_at(move.to_square)
        if victim is None or victim.color != color:
            continue
        after = board.copy(stack=False)
        after.push(move)
        best = max(best, _see_value(victim) - _exchange_gain(after, move.to_square, color))
    return best


def sacrificed_material(before: chess.Board, move: chess.Move) -> int:
    """Net material (cp) the mover offers with ``move``: what the opponent can win right
    after it, minus what the move itself captured. 0 for checkmating moves."""
    captured = 0
    if before.is_en_passant(move):
        captured = PIECE_VALUES[chess.PAWN]
    elif (victim := before.piece_at(move.to_square)) is not None:
        captured = PIECE_VALUES[victim.piece_type]
    after = before.copy(stack=False)
    after.push(move)
    if after.is_checkmate():
        return 0
    return material_exposed(after, before.turn) - captured


def _gives_mate(board: chess.Board, move: chess.Move) -> bool:
    after = board.copy(stack=False)
    after.push(move)
    return after.is_checkmate()


def _outcome(wc: float) -> int:
    if wc > OUTCOME_BUCKET_WC:
        return 1
    if wc < -OUTCOME_BUCKET_WC:
        return -1
    return 0


@dataclass(frozen=True)
class MoveContext:
    """What the classifier needs about one move. All ``wc_*`` values are winning chances
    from the mover's point of view."""

    board_before: chess.Board
    move: chess.Move
    loss: float
    wc_before: float
    wc_after: float
    is_engine_best: bool = False
    wc_second: float | None = None  # runner-up engine line in the position before the move
    in_book: bool = False
    opponent_loss: float | None = None  # loss of the opponent's previous move
    wc_before_opponent_move: float | None = None  # mover POV, before that previous move
    previous_move: chess.Move | None = None


def classify_move(ctx: MoveContext) -> MoveClassification:
    """Label one move. Thresholds and their order are documented in the module docstring."""
    loss = 0.0 if ctx.is_engine_best else ctx.loss
    if ctx.in_book and loss < INACCURACY_LOSS:
        return "book"
    if loss >= INACCURACY_LOSS:
        if (
            ctx.opponent_loss is not None
            and ctx.opponent_loss >= MISTAKE_LOSS
            and ctx.wc_before_opponent_move is not None
            and ctx.wc_after >= ctx.wc_before_opponent_move
        ):
            return "miss"
        return classify_win_chance_loss(loss)  # type: ignore[return-value]

    if (
        loss < EXCELLENT_LOSS
        and ctx.wc_before < BRILLIANT_MAX_WC_BEFORE
        and ctx.wc_after >= BRILLIANT_MIN_WC_AFTER
        and sacrificed_material(ctx.board_before, ctx.move) >= SACRIFICE_MIN_CP
    ):
        return "brilliant"

    best_class = ctx.is_engine_best or loss < BEST_LOSS
    if best_class and ctx.wc_second is not None and not _gives_mate(ctx.board_before, ctx.move):
        best_wc = max(ctx.wc_before, ctx.wc_after)
        recapture = (
            ctx.previous_move is not None
            and ctx.move.to_square == ctx.previous_move.to_square
            and ctx.board_before.is_capture(ctx.move)
        )
        if (
            not recapture
            and best_wc - ctx.wc_second >= GREAT_GAP
            and _outcome(best_wc) != _outcome(ctx.wc_second)
        ):
            return "great"
    if best_class:
        return "best"
    if loss < EXCELLENT_LOSS:
        return "excellent"
    return "good"
