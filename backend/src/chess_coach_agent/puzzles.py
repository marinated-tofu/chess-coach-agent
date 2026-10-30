"""Themed puzzle library built from a small subset of the Lichess puzzle database (CC0).

Puzzles back up the player's own mistakes: a practice session always starts with
positions from the player's games and only tops up with puzzles when those run short.

Stored puzzle shape (one JSON object per line in ``data/puzzles/puzzles.jsonl``):

    {"id": "00sHx", "fen": "<position after the opponent's first move>",
     "solution": ["e2e4", ...], "solution_san": "Qxe4", "rating": 1450,
     "theme": "missed_tactic", "tags": ["fork", "middlegame", ...]}

``fen`` is already the position the player must solve, so ``solution[0]`` is the
player's first move. Practice sessions grade only that first move; the puzzle page plays
the full line (see ``check_line``).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

import chess

PUZZLE_PATH = Path(__file__).resolve().parents[2] / "data" / "puzzles" / "puzzles.jsonl"

# Our coaching themes, in the priority order used to give each puzzle one primary theme.
# More specific themes win over generic ones, so a hanging piece in the opening counts as
# loose_piece and a mate in an endgame counts as endgame_conversion.
COACH_THEMES: tuple[str, ...] = (
    "loose_piece",
    "endgame_conversion",
    "opening_drift",
    "king_safety",
    "missed_tactic",
)

# Lichess puzzle theme tag -> our theme. See data/puzzles/README.md for the rationale.
LICHESS_THEME_MAP: dict[str, tuple[str, ...]] = {
    "loose_piece": ("hangingPiece",),
    "endgame_conversion": (
        "endgame",
        "rookEndgame",
        "pawnEndgame",
        "queenEndgame",
        "bishopEndgame",
        "knightEndgame",
        "queenRookEndgame",
    ),
    "opening_drift": ("opening",),
    "king_safety": (
        "kingsideAttack",
        "queensideAttack",
        "attackingF2F7",
        "exposedKing",
        "backRankMate",
        "smotheredMate",
        "mateIn1",
        "mateIn2",
        "mateIn3",
    ),
    "missed_tactic": (
        "fork",
        "pin",
        "skewer",
        "discoveredAttack",
        "doubleCheck",
        "deflection",
        "attraction",
        "interference",
        "clearance",
        "xRayAttack",
        "intermezzo",
        "capturingDefender",
        "trappedPiece",
        "sacrifice",
    ),
}

# Player-side theme names that differ from ours. Themes with no puzzle equivalent
# (time_pressure, candidate_move_discipline, ...) map to None: puzzles are untimed, so
# those players get a mixed pool across all themes.
THEME_ALIASES: dict[str, str] = {"loose_pieces": "loose_piece", "missed_tactics": "missed_tactic"}

# Puzzle page names. opening_drift and king_safety describe what the puzzles actually drill;
# see data/puzzles/README.md.
THEME_LABELS: dict[str, str] = {
    "loose_piece": "Hanging pieces",
    "endgame_conversion": "Endgames",
    "opening_drift": "Opening tactics",
    "king_safety": "King attacks",
    "missed_tactic": "Tactics",
}

DEFAULT_RATING = 1400
RATING_WINDOWS = (100, 200, 350, 600, 2000)


@dataclass(frozen=True)
class Puzzle:
    id: str
    fen: str
    solution: tuple[str, ...]
    solution_san: str
    rating: int
    theme: str
    tags: tuple[str, ...] = field(default_factory=tuple)


def map_lichess_themes(tags: Iterable[str]) -> str | None:
    """Return our primary theme for a set of Lichess theme tags, or None."""
    tag_set = set(tags)
    for theme in COACH_THEMES:
        if tag_set.intersection(LICHESS_THEME_MAP[theme]):
            return theme
    return None


def normalize_theme(theme: str | None) -> str | None:
    if not theme:
        return None
    theme = THEME_ALIASES.get(theme, theme)
    return theme if theme in COACH_THEMES else None


def _parse(line: str) -> Puzzle:
    raw = json.loads(line)
    return Puzzle(
        id=raw["id"],
        fen=raw["fen"],
        solution=tuple(raw["solution"]),
        solution_san=raw["solution_san"],
        rating=int(raw["rating"]),
        theme=raw["theme"],
        tags=tuple(raw.get("tags", ())),
    )


def load_puzzles(path: Path | None = None) -> list[Puzzle]:
    """Load the puzzle subset. Returns an empty list if the file is missing."""
    if path is None:
        return list(_load_default())
    return _load_path(path)


@lru_cache(maxsize=1)
def _load_default() -> tuple[Puzzle, ...]:
    return tuple(_load_path(PUZZLE_PATH))


def _load_path(path: Path) -> list[Puzzle]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [_parse(line) for line in handle if line.strip()]


def select_puzzles(
    theme: str | None,
    rating: int | None,
    count: int,
    exclude_ids: Iterable[str] = (),
    puzzles: Iterable[Puzzle] | None = None,
) -> list[Puzzle]:
    """Pick ``count`` puzzles for ``theme`` closest to ``rating``, skipping ``exclude_ids``.

    Unknown themes (or None) draw from every theme. The rating window widens until
    enough puzzles are found; within a window the closest ratings come first.
    """
    if count <= 0:
        return []
    pool = list(puzzles) if puzzles is not None else list(_load_default())
    excluded = set(exclude_ids)
    wanted = normalize_theme(theme)
    candidates = [
        item for item in pool if item.id not in excluded and (wanted is None or item.theme == wanted)
    ]
    target = rating or DEFAULT_RATING
    for window in RATING_WINDOWS:
        near = [item for item in candidates if abs(item.rating - target) <= window]
        if len(near) >= count or window == RATING_WINDOWS[-1]:
            near.sort(key=lambda item: (abs(item.rating - target), item.id))
            if wanted is None:
                return _round_robin(near, count)
            return near[:count]
    return []


def _round_robin(puzzles: list[Puzzle], count: int) -> list[Puzzle]:
    """Interleave themes so a mixed pool is not five puzzles of one theme."""
    by_theme: dict[str, list[Puzzle]] = {}
    for item in puzzles:
        by_theme.setdefault(item.theme, []).append(item)
    chosen: list[Puzzle] = []
    while len(chosen) < count and any(by_theme.values()):
        for theme in COACH_THEMES:
            if by_theme.get(theme) and len(chosen) < count:
                chosen.append(by_theme[theme].pop(0))
    return chosen


@lru_cache(maxsize=1)
def _by_id() -> dict[str, Puzzle]:
    return {item.id: item for item in _load_default()}


def get_puzzle(puzzle_id: str) -> Puzzle | None:
    return _by_id().get(puzzle_id)


def filter_puzzles(
    theme: str | None = None,
    min_rating: int | None = None,
    max_rating: int | None = None,
    puzzles: Iterable[Puzzle] | None = None,
) -> list[Puzzle]:
    """Puzzles for ``theme`` (None or unknown means every theme) within the rating range,
    easiest first. Unlike ``select_puzzles`` the range is strict: it never widens.
    """
    wanted = normalize_theme(theme)
    pool = puzzles if puzzles is not None else _load_default()
    return sorted(
        (
            item
            for item in pool
            if (wanted is None or item.theme == wanted)
            and (min_rating is None or item.rating >= min_rating)
            and (max_rating is None or item.rating <= max_rating)
        ),
        key=lambda item: (item.rating, item.id),
    )


@dataclass(frozen=True)
class LineCheck:
    status: Literal["continue", "solved", "wrong"]
    reply: str | None = None  # the opponent's answer in UCI, when status is "continue"


def check_line(puzzle: Puzzle, line: Sequence[str]) -> LineCheck:
    """Grade the newest move of ``line``, the UCI moves played so far from ``puzzle.fen``.

    Any move that gives checkmate solves the puzzle, as on Lichess. Raises ValueError when
    the line is not a position the player can be in: everything before the newest move must
    follow the solution, and the newest move must be the player's and legal.
    """
    index = len(line) - 1
    if index < 0 or index % 2 == 1 or index >= len(puzzle.solution):
        raise ValueError("Line does not end on the player's move")
    if list(line[:index]) != list(puzzle.solution[:index]):
        raise ValueError("Line left the solution")
    board = chess.Board(puzzle.fen)
    for uci in line[:index]:
        board.push_uci(uci)
    try:
        board.push_uci(line[index])
    except ValueError as exc:
        raise ValueError("Illegal move") from exc
    if board.is_checkmate():
        return LineCheck("solved")
    if line[index] != puzzle.solution[index]:
        return LineCheck("wrong")
    if index + 1 >= len(puzzle.solution):
        return LineCheck("solved")
    return LineCheck("continue", reply=puzzle.solution[index + 1])


def solution_sans(puzzle: Puzzle) -> list[str]:
    board = chess.Board(puzzle.fen)
    return [board.san_and_push(chess.Move.from_uci(uci)) for uci in puzzle.solution]
