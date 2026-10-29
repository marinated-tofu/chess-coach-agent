"""Opening classification from the lichess-org/chess-openings dataset (CC0).

The dataset lists each named opening as an ECO code, a name and a PGN line.
We replay every line once, key the final position by its EPD (board, side to
move, castling rights, en passant square), and classify a game by the deepest
position along its moves that matches a named line. Matching by position
instead of by move order means transpositions get the right name.
"""

from __future__ import annotations

import csv
import io
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import chess
import chess.pgn

OPENINGS_DIR = Path(__file__).resolve().parents[2] / "data" / "openings"
TSV_FILES = ("a.tsv", "b.tsv", "c.tsv", "d.tsv", "e.tsv")
# The longest named line in the dataset is under 40 plies; scanning a little
# further lets late transpositions into book still match.
MAX_BOOK_PLY = 50


@dataclass(frozen=True)
class Opening:
    eco: str
    name: str
    ply: int  # length of the dataset line that names this position

    @property
    def family(self) -> str:
        return self.name.split(":", 1)[0].strip()


@dataclass(frozen=True)
class OpeningMatch:
    opening: Opening
    book_ply: int  # last ply of the game that was still a named position


def fen_to_epd(fen: str) -> str:
    """First four FEN fields. python-chess writes FENs and EPDs with the same
    'legal' en passant rule, so this equals ``chess.Board(fen).epd()``."""
    return " ".join(fen.split(" ", 4)[:4])


def _lines(directory: Path) -> Iterable[tuple[str, str, str]]:
    for filename in TSV_FILES:
        path = directory / filename
        if not path.exists():
            continue
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                yield row["eco"], row["name"], row["pgn"]


_BOOK_LOCK = threading.Lock()


def opening_book(directory: Path = OPENINGS_DIR) -> dict[str, Opening]:
    """Map EPD -> Opening. Built once per process (~3.9k lines, under a second)."""
    with _BOOK_LOCK:
        return _build_book(directory)


@lru_cache(maxsize=4)
def _build_book(directory: Path) -> dict[str, Opening]:
    book: dict[str, Opening] = {}
    for eco, name, pgn in _lines(directory):
        game = chess.pgn.read_game(io.StringIO(pgn))
        if game is None:
            continue
        board = game.board()
        ply = 0
        for move in game.mainline_moves():
            board.push(move)
            ply += 1
        epd = board.epd()
        existing = book.get(epd)
        # When two lines reach the same position, keep the shorter, more
        # general one; ties keep the first in file order.
        if existing is None or ply < existing.ply:
            book[epd] = Opening(eco=eco, name=name, ply=ply)
    return book


def classify_fens(fens_after: Iterable[str]) -> OpeningMatch | None:
    """Classify by the deepest book position in a sequence of FENs (one per ply)."""
    book = opening_book()
    match: OpeningMatch | None = None
    for ply, fen in enumerate(fens_after, start=1):
        if ply > MAX_BOOK_PLY:
            break
        opening = book.get(fen_to_epd(fen))
        if opening is not None:
            match = OpeningMatch(opening=opening, book_ply=ply)
    return match


def classify_moves(moves: Iterable[dict | object]) -> OpeningMatch | None:
    """Classify stored moves (MoveRecord objects or their JSON dicts)."""

    def fen_after(move: dict | object) -> str:
        if isinstance(move, dict):
            return str(move.get("fen_after", ""))
        return str(getattr(move, "fen_after", ""))

    return classify_fens(fen_after(move) for move in moves)


def classify_sans(sans: Iterable[str], start_fen: str = chess.STARTING_FEN) -> OpeningMatch | None:
    """Classify a SAN move list, e.g. ``["e4", "e5", "Nf3"]``."""
    board = chess.Board(start_fen)
    fens: list[str] = []
    for san in sans:
        board.push_san(san)
        fens.append(board.fen())
    return classify_fens(fens)


def label_game(moves: Iterable[dict | object]) -> dict[str, str | int] | None:
    """Opening label for one game, for the review header."""
    match = classify_moves(moves)
    if match is None:
        return None
    return {
        "eco": match.opening.eco,
        "name": match.opening.name,
        "family": match.opening.family,
        "book_ply": match.book_ply,
    }
