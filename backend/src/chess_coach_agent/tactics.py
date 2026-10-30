"""Tactics found and missed: forks, pins, skewers and mates in a player's analyzed games.

Works only from what sync stored in ``GameRow.metadata_json["moves"]``. Stockfish never runs
here. Each ply stores ``best_uci`` (the engine's move in the position before it) and
``eval_cp`` / ``eval_mate`` (White's score after it), so the score of the position a player
faced is the stored score of the ply before.

A position counts as a chance only when all of these hold. They are deliberately strict: a
missed count that is wrong does more harm than one that is short.

Mate
    The stored score says the player mates in at most ``MAX_MATE`` moves. A mate in 1 must
    also be checkmate when ``best_uci`` is played on the board.

Fork, skewer, pin, mate threat
    1. Eval: the stored score beats the material on the board by ``MIN_GAIN_CP``, so the engine
       sees something the piece count does not show yet.
    2. Geometry: ``best_uci`` creates the motif (see below).
    3. Proof: against *every* legal reply the player has a capture that nets at least
       ``MIN_GAIN_CP`` after the static exchange, not counting what ``best_uci`` itself took.
       That capture must take one of the motif's pieces, made by the piece(s) that created
       it. For a mate threat, any capture counts, and so does mate in 1.

Motifs, read off the board after ``best_uci``:

* fork: the moved piece attacks two or more pieces, each the enemy king or a piece it would
  win at least ``MIN_GAIN_CP`` by taking. The winning capture must be made by that piece.
* skewer: the moved bishop, rook or queen lines up on a piece with a cheaper one behind it,
  not a pawn.
* pin: the same with a dearer piece (or the king) behind it. So does a safe move that attacks
  a piece already pinned, because that is how pins win material.
* mate threat: a quiet move after which mate in 1 would follow if the opponent passed.

How a chance is scored:

* found: the player played ``best_uci``. For mates, any move that keeps the forced mate.
* missed: the player's move lost at least ``MIN_GAIN_CP`` by the stored scores. For mates: a
  mate in 1 not played, or a longer mate given up for a score under ``STILL_WINNING_CP``.
* neither: a different move that keeps most of the advantage. It is left out of both counts,
  because it was not the tactic but it was no miss either.

A forced mate played out over several moves is one chance, not one per move.

Combinations that begin with a sacrifice, discovered attacks and anything needing more than
one reply to prove are not counted. Recall is traded for precision on purpose.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

import chess
from pydantic import BaseModel

from .classification import _exchange_gain, _see_value
from .engine import MATE_CP, PIECE_VALUES

Motif = Literal["fork", "pin", "skewer", "mate_threat", "mate_1", "mate_2", "mate_3"]

# Bump when detection changes, so cached per-game results are recomputed.
TACTICS_VERSION = 1

MIN_GAIN_CP = 150  # less than the exchange (500 - 320), more than a pawn
# After a longer mate is passed up, a score this high usually hides a mate the stored search
# was too shallow to see, so the move is not called a miss. A skipped mate in 1 always is.
STILL_WINNING_CP = 600
MAX_MATE = 5  # mates longer than this are not a fair thing to expect a player to see
MIN_CHANCES = 10  # below this a rate is noise: show the counts, not the percentage
MAX_EXAMPLES = 3

# (motif, label, puzzle tag). Tags are the Lichess ones stored on each puzzle.
MOTIFS: tuple[tuple[Motif, str, str], ...] = (
    ("fork", "Forks", "fork"),
    ("pin", "Pins", "pin"),
    ("skewer", "Skewers", "skewer"),
    ("mate_threat", "Mate threats", "mate"),
    ("mate_1", "Mate in 1", "mateIn1"),
    ("mate_2", "Mate in 2", "mateIn2"),
    ("mate_3", "Mate in 3+", "mate"),
)

_SLIDERS = (chess.BISHOP, chess.ROOK, chess.QUEEN)
_PIECE_POINTS = {
    "p": PIECE_VALUES[chess.PAWN],
    "n": PIECE_VALUES[chess.KNIGHT],
    "b": PIECE_VALUES[chess.BISHOP],
    "r": PIECE_VALUES[chess.ROOK],
    "q": PIECE_VALUES[chess.QUEEN],
}


class TacticExample(BaseModel):
    game_id: str
    ply: int
    move_number: int
    color: Literal["white", "black"]
    played_san: str
    best_san: str
    fen: str


class TacticRow(BaseModel):
    motif: Motif
    label: str
    found: int = 0
    missed: int = 0
    chances: int = 0
    low_sample: bool = True  # fewer than min_chances: counts only, no rate
    found_pct: float | None = None
    found_low_pct: float | None = None  # 95% interval
    found_high_pct: float | None = None
    practice_tag: str
    examples: list[TacticExample] = []  # latest missed chances


class TacticsSection(BaseModel):
    sample_size: int = 0  # games with stored engine moves and scores
    games_without_evals: int = 0  # left out: older analyses, a full re-sync adds them
    min_chances: int = MIN_CHANCES
    found: int = 0
    missed: int = 0
    rows: list[TacticRow] = []


@dataclass(frozen=True)
class Chance:
    motif: Motif
    found: bool
    ply: int
    move_number: int
    color: str
    played_san: str
    best_san: str
    fen: str


# --------------------------------------------------------------------------- geometry


def _material_from_fen(fen: str, color: bool) -> int:
    """Material balance for ``color`` from the FEN string, without building a Board."""
    total = 0
    for char in fen.split(" ", 1)[0]:
        points = _PIECE_POINTS.get(char.lower())
        if points is not None:
            total += points if char.isupper() == (color == chess.WHITE) else -points
    return total


def _rank_value(piece: chess.Piece) -> int:
    return 100_000 if piece.piece_type == chess.KING else PIECE_VALUES[piece.piece_type]


def _captured_value(board: chess.Board, move: chess.Move) -> int:
    if board.is_en_passant(move):
        return PIECE_VALUES[chess.PAWN]
    victim = board.piece_at(move.to_square)
    return PIECE_VALUES[victim.piece_type] if victim else 0


def _capture_gain(board: chess.Board, move: chess.Move) -> int:
    """Net material from the capture ``move`` once the static exchange is over."""
    value = _captured_value(board, move)
    board.push(move)
    gain = value - _exchange_gain(board, move.to_square, board.turn)
    board.pop()
    return gain


def _attack_gain(board: chess.Board, source: chess.Square, target: chess.Square) -> int:
    """What the piece on ``source`` nets by taking ``target``, whoever's turn it is."""
    piece = board.piece_at(source)
    victim = board.piece_at(target)
    assert piece is not None and victim is not None
    probe = board.copy(stack=False)
    probe.remove_piece_at(source)
    probe.set_piece_at(target, piece)
    return _see_value(victim) - _exchange_gain(probe, target, victim.color)


def _forced_gain(
    board: chess.Board,
    spent: int,
    pieces: Iterable[chess.Square] | None = None,
    targets: Iterable[chess.Square] | None = None,
    mate_counts: bool = False,
) -> int:
    """The least the side not to move can win against any reply on ``board``.

    A capture counts only if it is made by one of ``pieces`` and takes one of ``targets``
    (followed if it moved); None means any. ``spent`` is what the tactic move itself captured:
    a reply may take that much back for free, and it is not part of the gain. With
    ``mate_counts``, a reply that allows mate in 1 counts as won.
    """
    squares = None if pieces is None else set(pieces)
    wanted = None if targets is None else set(targets)
    worst: int | None = None
    for reply in list(board.legal_moves):
        lost = _captured_value(board, reply)
        hit = wanted
        if wanted is not None and reply.from_square in wanted:
            hit = (wanted - {reply.from_square}) | {reply.to_square}
        board.push(reply)
        if board.is_checkmate():
            board.pop()
            return 0
        gain = 0
        for move in list(board.legal_moves):
            if mate_counts and _gives_mate(board, move):
                gain = _see_value(chess.Piece(chess.KING, not board.turn))
                break
            if squares is not None and move.from_square not in squares:
                continue
            if hit is not None and move.to_square not in hit:
                continue
            if board.is_capture(move):
                gain = max(gain, _capture_gain(board, move))
        board.pop()
        net = gain - max(0, lost - spent)
        worst = net if worst is None else min(worst, net)
        if worst < MIN_GAIN_CP:
            return worst
    return worst or 0


def _gives_mate(board: chess.Board, move: chess.Move) -> bool:
    board.push(move)
    mate = board.is_checkmate()
    board.pop()
    return mate


def _has_mate_in_one(board: chess.Board) -> bool:
    return any(_gives_mate(board, move) for move in list(board.legal_moves))


def _is_fork(after: chess.Board, square: chess.Square, spent: int) -> bool:
    piece = after.piece_at(square)
    if piece is None:
        return False
    targets = [
        target
        for target in after.attacks(square)
        if (victim := after.piece_at(target)) is not None
        and victim.color != piece.color
        and (victim.piece_type == chess.KING or _attack_gain(after, square, target) >= MIN_GAIN_CP)
    ]
    return len(targets) >= 2 and _forced_gain(after, spent, [square], targets) >= MIN_GAIN_CP


def _piece_behind(
    board: chess.Board, source: chess.Square, front: chess.Square
) -> chess.Square | None:
    """The first piece past ``front`` on the line from ``source``, or None."""
    file_step = chess.square_file(front) - chess.square_file(source)
    rank_step = chess.square_rank(front) - chess.square_rank(source)
    file_step = (file_step > 0) - (file_step < 0)
    rank_step = (rank_step > 0) - (rank_step < 0)
    file_at, rank_at = chess.square_file(front), chess.square_rank(front)
    while True:
        file_at += file_step
        rank_at += rank_step
        if not (0 <= file_at < 8 and 0 <= rank_at < 8):
            return None
        square = chess.square(file_at, rank_at)
        if board.piece_at(square) is not None:
            return square


def _line_motif(
    before: chess.Board, after: chess.Board, best: chess.Move, spent: int
) -> Motif | None:
    """Skewer or pin along any of the mover's lines; the skewer wins a tie."""
    mover = before.turn
    moved_to = best.to_square
    if after.checkers() - chess.SquareSet.from_square(moved_to):
        return None  # a discovered check, which is what wins the material
    found: set[Motif] = set()
    for piece_type in _SLIDERS:
        for slider in after.pieces(piece_type, mover):
            for front in after.attacks(slider) & after.occupied_co[not mover]:
                rear = _piece_behind(after, slider, front)
                if rear is None or after.color_at(rear) == mover:
                    continue
                front_value = _rank_value(after.piece_at(front))  # type: ignore[arg-type]
                rear_value = _rank_value(after.piece_at(rear))  # type: ignore[arg-type]
                if abs(front_value - rear_value) < PIECE_VALUES[chess.PAWN]:
                    continue
                motif: Motif = "skewer" if front_value > rear_value else "pin"
                if motif == "skewer" and rear_value == PIECE_VALUES[chess.PAWN]:
                    continue  # that is an attack on the front piece, not a skewer
                if slider != moved_to and not (
                    motif == "pin"
                    and front in before.attacks(slider)  # the pin was already there
                    and front in after.attacks(moved_to)
                    and not any(reply.to_square == moved_to for reply in after.legal_moves)
                ):
                    continue
                if motif in found:
                    continue
                if _forced_gain(after, spent, {slider, moved_to}, {front, rear}) >= MIN_GAIN_CP:
                    found.add(motif)
    if "skewer" in found:
        return "skewer"
    return "pin" if "pin" in found else None


def _is_mate_threat(after: chess.Board, spent: int) -> bool:
    if after.is_check():
        return False
    after.push(chess.Move.null())
    threat = _has_mate_in_one(after)
    after.pop()
    return threat and _forced_gain(after, spent, mate_counts=True) >= MIN_GAIN_CP


def detect_material_motif(board: chess.Board, best: chess.Move) -> Motif | None:
    """The motif ``best`` creates in ``board`` that is proved to win material, if any."""
    spent = _captured_value(board, best)
    after = board.copy(stack=False)
    after.push(best)
    if _is_fork(after, best.to_square, spent):
        return "fork"
    line = _line_motif(board, after, best, spent)
    if line:
        return line
    if _is_mate_threat(after, spent):
        return "mate_threat"
    return None


def _mate_motif(moves_to_mate: int) -> Motif:
    return "mate_1" if moves_to_mate == 1 else "mate_2" if moves_to_mate == 2 else "mate_3"


# --------------------------------------------------------------------------- a game


def has_stored_evals(moves: list[dict[str, Any]]) -> bool:
    return bool(moves) and all(
        m.get("best_uci") and m.get("fen_before") and (m.get("eval_cp") is not None or m.get("eval_mate") is not None)
        for m in moves
    )


def _score(move: dict[str, Any], color: bool) -> tuple[int, int | None]:
    """(centipawns with mates folded in, moves to mate or None) for ``color`` after ``move``."""
    sign = 1 if color == chess.WHITE else -1
    mate = move.get("eval_mate")
    if mate is not None:
        if mate == 0:  # checkmate on the board: the side to move has lost
            winner_is_white = " b " in move.get("fen_after", "")
            return (MATE_CP * (1 if winner_is_white else -1) * sign, None)
        return (MATE_CP if mate > 0 else -MATE_CP) * sign, mate * sign
    return move["eval_cp"] * sign, None


def _legal_best(board: chess.Board, uci: str) -> chess.Move | None:
    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        return None
    return move if board.is_legal(move) else None


def _chance(motif: Motif, found: bool, record: dict[str, Any]) -> Chance:
    return Chance(
        motif=motif,
        found=found,
        ply=record["ply"],
        move_number=record["move_number"],
        color=record["color"],
        played_san=record["san"],
        best_san=record.get("best_san") or record["best_uci"],
        fen=record["fen_before"],
    )


def game_chances(moves: list[dict[str, Any]], player_color: str) -> list[Chance]:
    """Every tactical chance the player had in one game (see the module docstring)."""
    color = chess.WHITE if player_color == "white" else chess.BLACK
    chances: list[Chance] = []
    mating: Chance | None = None  # a forced mate the player is playing out
    for previous, record in zip(moves, moves[1:]):
        if record.get("color") != player_color:
            continue
        value, moves_to_mate = _score(previous, color)
        played_value, played_mate = _score(record, color)
        played_uci, best_uci = record["uci"], record["best_uci"]
        has_mate = moves_to_mate is not None and 0 < moves_to_mate <= MAX_MATE
        if mating is not None and not has_mate:
            chances.append(mating)
            mating = None
        if has_mate:
            assert moves_to_mate is not None
            board = chess.Board(record["fen_before"])
            best = _legal_best(board, best_uci)
            if best is None or (moves_to_mate == 1 and not _gives_mate(board, best)):
                continue
            mated = record.get("eval_mate") == 0
            kept = mated or played_uci == best_uci or (played_mate is not None and played_mate > 0)
            if kept:
                mating = mating or _chance(_mate_motif(moves_to_mate), True, record)
                if mated:
                    chances.append(mating)
                    mating = None
            elif moves_to_mate == 1 or played_value < STILL_WINNING_CP:
                chances.append(_chance(_mate_motif(moves_to_mate), False, record))
                mating = None
            else:
                mating = None
            continue
        if moves_to_mate is not None:  # a long mate, or the player is being mated
            continue
        if value - _material_from_fen(record["fen_before"], color) < MIN_GAIN_CP:
            continue
        found = played_uci == best_uci
        if not found and value - played_value < MIN_GAIN_CP:
            continue
        board = chess.Board(record["fen_before"])
        best = _legal_best(board, best_uci)
        motif = detect_material_motif(board, best) if best is not None else None
        if motif is not None:
            chances.append(_chance(motif, found, record))
    if mating is not None:
        chances.append(mating)
    return chances


_GAME_CACHE: OrderedDict[str, tuple[int, list[Chance]]] = OrderedDict()
_GAME_CACHE_SIZE = 50_000


def cached_game_chances(
    game_key: str, moves: list[dict[str, Any]], player_color: str
) -> list[Chance]:
    """``game_chances`` remembered per game. A full history takes seconds of python-chess, and
    the Insights response cache rebuilds everything whenever one new game arrives. The
    fingerprint changes when a re-analysis rewrites the game's engine data."""
    fingerprint = hash(
        (TACTICS_VERSION, tuple((m["best_uci"], m.get("eval_cp"), m.get("eval_mate")) for m in moves))
    )
    cached = _GAME_CACHE.get(game_key)
    if cached is not None and cached[0] == fingerprint:
        return cached[1]
    chances = game_chances(moves, player_color)
    _GAME_CACHE[game_key] = (fingerprint, chances)
    while len(_GAME_CACHE) > _GAME_CACHE_SIZE:
        try:
            _GAME_CACHE.popitem(last=False)
        except KeyError:  # another request emptied it first
            break
    return chances
