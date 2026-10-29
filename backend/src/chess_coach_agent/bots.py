"""Human-like bot opponents built on Stockfish.

lc0 + Maia nets are not installed here, so the bots use a documented move model on top of a
shallow Stockfish MultiPV search instead. The model follows what lila's Stockfish levels and the
Maia papers (McIlroy-Young et al., 2020) observed about human play:

* Humans pick plausible moves. Every bot samples from the engine's top candidates with a softmax
  over ``-loss / temperature``, where ``loss`` is the drop in win% (Lichess win% formula) against
  the best candidate. A cold temperature means "nearly always the best move"; a warm one spreads
  the choice across reasonable-looking moves.
* Error rate scales with rating. Both the temperature and a separate blunder chance fall off
  exponentially with rating (see ``temperature`` and ``blunder_chance``):

      rating   temperature (win%)   blunder chance per move
      600      14.0                 25%
      1200      5.2                  6.6%  (about 1 in 15 moves)
      1600      2.7                  2.7%
      2000      1.4                  1.1%
      2200      1.0                  0.7%

* Blunders cluster in complex positions. The blunder chance is multiplied by a complexity factor
  between 0.5 and 1.6: positions where only one move holds (a big gap between the best and the
  third-best candidate), checks, and many captures on the board raise it; quiet positions with
  several equal moves lower it. A blunder picks a candidate that loses at least 8 win%, or failing
  that a random "active-looking" legal move outside the engine's top two (humans blunder with
  captures and checks far more often than with quiet retreats).
* Styles add bonus logits on top of the softmax, so they only change choices between moves that
  are close in value: "aggressive" likes checks, captures and moves into the enemy king zone;
  "tricky" likes baits (a piece left capturable while the engine still rates the move fine) and
  quiet checks; "solid" likes castling, development and recaptures, and plays a little colder.
* In the opening (the first ``book_plies`` plies, 6 for a 600 bot up to 14 for 2200) the bot plays
  from a book. The "sparring" bot uses the moves the player's real opponents chose in this exact
  position in the player's stored games, frequency-weighted; every bot falls back to the Lichess
  openings TSV (popular named lines), weighted by how many named lines continue with each move.
"""

from __future__ import annotations

import csv
import io
import math
import random
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

import chess
import chess.engine
import chess.pgn

from .openings import OPENINGS_DIR, TSV_FILES, fen_to_epd

Style = Literal["solid", "aggressive", "tricky", "sparring"]

MULTIPV = 8
BLUNDER_LOSS = 8.0  # win% a candidate must lose to count as a blunder pick
SPARRING_MAX_PLY = 16  # how deep into stored games the sparring book reads
BOT_SUFFIX = "(bot)"  # the Play page names the bot "<name> (bot)" in exported PGNs


@dataclass(frozen=True)
class BotPersona:
    id: str
    name: str
    rating: int
    style: Style
    blurb: str
    initial: str
    color: str  # avatar background


BOTS: tuple[BotPersona, ...] = (
    BotPersona("theo", "Theo", 600, "aggressive", "Gives every check he sees. Leaves pieces hanging.", "T", "#c2410c"),
    BotPersona("mara", "Mara", 900, "solid", "Castles early, trades when unsure, rarely attacks.", "M", "#4d7c0f"),
    BotPersona("kit", "Kit", 1200, "tricky", "Sets cheap traps and hopes you take the bait.", "K", "#7c3aed"),
    BotPersona("dmitri", "Dmitri", 1500, "aggressive", "Throws pawns at your king and sacrifices on a hunch.", "D", "#b91c1c"),
    BotPersona(
        "sparring",
        "Sparring partner",
        1500,
        "sparring",
        "Plays the openings your real opponents play against you. Plays at your rating when it knows it.",
        "S",
        "#0f766e",
    ),
    BotPersona("ines", "Ines", 1800, "solid", "Positional and patient. Wins the endgames you thought were drawn.", "I", "#1d4ed8"),
    BotPersona("viktor", "Viktor", 2000, "tricky", "Plays for swindles in worse positions and rarely misses one.", "V", "#6d28d9"),
    BotPersona("lena", "Lena", 2200, "solid", "Club master strength. Punishes loose moves.", "L", "#0f172a"),
)
BOTS_BY_ID = {bot.id: bot for bot in BOTS}


# --- rating curves ---------------------------------------------------------------------------


def temperature(rating: int) -> float:
    """Softmax temperature in win% units: 14 at 600, ~5 at 1200, ~1.4 at 2000."""
    return max(0.6, 14.0 * math.exp(-(rating - 600) / 600))


def blunder_chance(rating: int) -> float:
    """Base chance per move to blunder: 25% at 600, ~6.6% (1 in 15) at 1200, ~1% at 2000."""
    return min(0.3, 0.25 * math.exp(-(rating - 600) / 450))


def book_plies(rating: int) -> int:
    return int(min(14, max(6, 6 + (rating - 600) / 200)))


def search_depth(rating: int) -> int:
    """Shallow search, like lila's low levels; deeper for stronger bots so the losses are real."""
    return int(min(12, max(6, 6 + (rating - 600) / 250)))


def win_pct(cp: int) -> float:
    """Lichess win% for centipawns from the mover's point of view."""
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


# --- candidates ------------------------------------------------------------------------------


@dataclass
class Candidate:
    move: chess.Move
    win: float  # win% for the side to move after this move
    loss: float = 0.0  # win% lost against the best candidate


@dataclass
class Decision:
    move: chess.Move
    source: Literal["book", "sparring", "engine", "blunder", "only"]
    loss: float | None = None  # None when the move came from outside the analysed candidates
    complexity: float = 1.0
    book_games: int = 0
    note: str | None = None


def analyse_candidates(engine: chess.engine.SimpleEngine, board: chess.Board, rating: int) -> list[Candidate]:
    limit = chess.engine.Limit(depth=search_depth(rating), time=0.4)
    multipv = min(MULTIPV, board.legal_moves.count())
    infos = engine.analyse(board, limit, multipv=multipv)
    candidates: list[Candidate] = []
    seen: set[chess.Move] = set()
    for info in infos:
        pv = info.get("pv") or []
        if not pv or "score" not in info or pv[0] in seen:
            continue
        seen.add(pv[0])
        cp = info["score"].pov(board.turn).score(mate_score=100_000)
        candidates.append(Candidate(move=pv[0], win=win_pct(cp)))
    if candidates:
        best = max(candidate.win for candidate in candidates)
        for candidate in candidates:
            candidate.loss = best - candidate.win
        candidates.sort(key=lambda candidate: candidate.loss)
    return candidates


def complexity(board: chess.Board, candidates: list[Candidate]) -> float:
    """0.5 (quiet, many equal moves) to 1.6 (sharp: one move holds, checks, lots of captures)."""
    score = 1.0
    if len(candidates) >= 3:
        gap = candidates[2].loss
        score += min(0.4, gap / 25) - (0.3 if gap < 2 else 0.0)
    if board.is_check():
        score += 0.2
    captures = sum(1 for move in board.legal_moves if board.is_capture(move))
    score += min(0.2, captures * 0.03)
    return max(0.5, min(1.6, score))


# --- styles ----------------------------------------------------------------------------------


def _king_zone(board: chess.Board, color: chess.Color) -> chess.SquareSet:
    king = board.king(color)
    if king is None:
        return chess.SquareSet()
    return chess.SquareSet(chess.BB_KING_ATTACKS[king] | chess.BB_SQUARES[king])


def style_bonus(board: chess.Board, candidate: Candidate, style: Style) -> float:
    move = candidate.move
    bonus = 0.0
    gives_check = board.gives_check(move)
    capture = board.is_capture(move)
    if style == "aggressive":
        if gives_check:
            bonus += 0.8
        if capture:
            bonus += 0.4
        after = board.copy(stack=False)
        after.push(move)
        zone = _king_zone(after, after.turn)
        if move.to_square in zone or after.attacks(move.to_square) & zone:
            bonus += 0.4
    elif style == "tricky":
        if candidate.loss < 4:
            after = board.copy(stack=False)
            after.push(move)
            baits = any(after.is_capture(reply) for reply in after.legal_moves)
            if baits and not capture:
                bonus += 0.7  # leaves something to grab while the engine says it's fine
        if gives_check and not capture:
            bonus += 0.3
    elif style == "solid":
        if board.is_castling(move):
            bonus += 1.0
        piece = board.piece_at(move.from_square)
        home_rank = 0 if board.turn == chess.WHITE else 7
        if piece and piece.piece_type in (chess.KNIGHT, chess.BISHOP) and chess.square_rank(move.from_square) == home_rank:
            bonus += 0.4
        if capture and board.move_stack and board.peek().to_square == move.to_square:
            bonus += 0.4  # recapture
        if gives_check and not capture:
            bonus -= 0.2
    return bonus


# --- sampling --------------------------------------------------------------------------------


def _active_weight(board: chess.Board, move: chess.Move) -> float:
    weight = 1.0
    if board.is_capture(move):
        weight += 2.0
    if board.gives_check(move):
        weight += 1.5
    piece = board.piece_at(move.from_square)
    if piece and piece.piece_type == chess.QUEEN:
        weight += 0.5
    return weight


def choose_from_candidates(
    board: chess.Board,
    candidates: list[Candidate],
    rating: int,
    style: Style,
    rng: random.Random,
) -> Decision:
    if not candidates:
        raise ValueError("No candidates to choose from.")
    sharpness = complexity(board, candidates)
    if len(candidates) == 1 and board.legal_moves.count() == 1:
        return Decision(candidates[0].move, "only", 0.0, sharpness)

    if rng.random() < blunder_chance(rating) * sharpness:
        losing = [candidate for candidate in candidates if candidate.loss >= BLUNDER_LOSS]
        if losing:
            pick = rng.choice(losing)
            return Decision(pick.move, "blunder", pick.loss, sharpness)
        top = {candidate.move for candidate in candidates[:2]}
        others = [move for move in board.legal_moves if move not in top]
        if others:
            weights = [_active_weight(board, move) for move in others]
            move = rng.choices(others, weights=weights, k=1)[0]
            known = next((c.loss for c in candidates if c.move == move), None)
            return Decision(move, "blunder", known, sharpness)

    temp = temperature(rating) * (0.85 if style == "solid" else 1.0)
    logits = [-candidate.loss / temp + style_bonus(board, candidate, style) for candidate in candidates]
    top = max(logits)
    weights = [math.exp(logit - top) for logit in logits]
    pick = rng.choices(candidates, weights=weights, k=1)[0]
    return Decision(pick.move, "engine", pick.loss, sharpness)


# --- books -----------------------------------------------------------------------------------


@lru_cache(maxsize=1)
def tsv_book(directory: Path = OPENINGS_DIR) -> dict[str, Counter[str]]:
    """EPD -> Counter(uci) of the next move in every named Lichess line that passes through it."""
    book: dict[str, Counter[str]] = defaultdict(Counter)
    for filename in TSV_FILES:
        path = directory / filename
        if not path.exists():
            continue
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                game = chess.pgn.read_game(io.StringIO(row["pgn"]))
                if game is None:
                    continue
                board = game.board()
                for move in game.mainline_moves():
                    book[board.epd()][move.uci()] += 1
                    board.push(move)
    return dict(book)


_SPARRING_CACHE: dict[tuple[str, str], tuple[int, dict[str, Counter[str]]]] = {}
_SPARRING_LOCK = threading.Lock()


def sparring_book(platform: str | None, username: str) -> dict[str, Counter[str]]:
    """EPD -> Counter(uci) of the moves the player's opponents played, from stored games.

    Only ``metadata_json`` is read and only the first ``SPARRING_MAX_PLY`` plies are kept. The
    result is cached per player and rebuilt when the stored game count changes.
    """
    from sqlalchemy import func, select

    from .db import session_scope
    from .db_models import GameRow, PlayerRow
    from .repositories import normalize_username

    normalized = normalize_username(username)
    if not normalized:
        return {}
    key = (platform or "*", normalized)
    with session_scope() as session:
        query = select(PlayerRow.id).where(PlayerRow.username_normalized == normalized)
        if platform:
            query = query.where(PlayerRow.platform == platform)
        player_ids = list(session.scalars(query))
        if not player_ids:
            return {}
        count = session.scalar(select(func.count(GameRow.id)).where(GameRow.player_id.in_(player_ids))) or 0
        with _SPARRING_LOCK:
            cached = _SPARRING_CACHE.get(key)
            if cached and cached[0] == count:
                return cached[1]
        book: dict[str, Counter[str]] = defaultdict(Counter)
        rows = session.execute(
            select(GameRow.white, GameRow.black, GameRow.metadata_json).where(GameRow.player_id.in_(player_ids))
        )
        for white, black, stored in rows:
            if (white or "").endswith(BOT_SUFFIX) or (black or "").endswith(BOT_SUFFIX):
                continue  # games played against these bots would only echo the bots themselves
            for move in ((stored or {}).get("moves") or [])[:SPARRING_MAX_PLY]:
                if not isinstance(move, dict) or move.get("is_player_move", True):
                    continue
                fen, uci = move.get("fen_before"), move.get("uci")
                if fen and uci:
                    book[fen_to_epd(fen)][uci] += 1
    result = dict(book)
    with _SPARRING_LOCK:
        _SPARRING_CACHE[key] = (count, result)
    return result


def player_rating(platform: str | None, username: str) -> int | None:
    from sqlalchemy import select

    from .db import session_scope
    from .db_models import PlayerRow
    from .repositories import normalize_username

    with session_scope() as session:
        query = select(PlayerRow.current_rating).where(
            PlayerRow.username_normalized == normalize_username(username),
            PlayerRow.current_rating.is_not(None),
        )
        if platform:
            query = query.where(PlayerRow.platform == platform)
        return session.scalars(query).first()


def book_pick(board: chess.Board, book: dict[str, Counter[str]], rng: random.Random) -> tuple[chess.Move, int] | None:
    counts = book.get(board.epd())
    if not counts:
        return None
    legal = [(chess.Move.from_uci(uci), n) for uci, n in counts.items() if chess.Move.from_uci(uci) in board.legal_moves]
    if not legal:
        return None
    move = rng.choices([move for move, _ in legal], weights=[n for _, n in legal], k=1)[0]
    return move, sum(n for _, n in legal)


# --- top level -------------------------------------------------------------------------------


@dataclass
class BotContext:
    bot: BotPersona
    rating: int
    ply: int  # plies already played in this game
    sparring: dict[str, Counter[str]] = field(default_factory=dict)


def choose_move(
    engine: chess.engine.SimpleEngine | None,
    board: chess.Board,
    context: BotContext,
    rng: random.Random,
) -> Decision:
    """Pick the bot's move. ``engine`` may be None only when a book move is guaranteed."""
    if context.ply < book_plies(context.rating) + (4 if context.bot.style == "sparring" else 0):
        if context.sparring:
            picked = book_pick(board, context.sparring, rng)
            if picked:
                return Decision(picked[0], "sparring", None, 1.0, picked[1])
        if context.ply < book_plies(context.rating):
            picked = book_pick(board, tsv_book(), rng)
            if picked:
                return Decision(picked[0], "book", None, 1.0, picked[1])
    if engine is None:
        raise ValueError("An engine is required outside the book.")
    candidates = analyse_candidates(engine, board, context.rating)
    if not candidates:
        move = next(iter(board.legal_moves))
        return Decision(move, "only", None)
    return choose_from_candidates(board, candidates, context.rating, context.bot.style, rng)


def thinking_ms(decision: Decision, rating: int, rng: random.Random) -> int:
    """A delay hint for the UI so replies don't land instantly. Book moves are quick; sharp
    positions take longer; stronger bots think a bit longer on average."""
    if decision.source in ("book", "sparring", "only"):
        return int(rng.uniform(350, 900))
    base = 500 + (rating - 600) * 0.6
    return int(min(4000, base * decision.complexity * rng.uniform(0.7, 1.4)))
