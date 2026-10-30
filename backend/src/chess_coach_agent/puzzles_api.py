"""The puzzle page: browse the library by theme and rating, solve puzzles move by move.

Solutions stay on the server until a puzzle is over. The page posts the line played so far
and gets back the verdict and the opponent's reply, so ``check_line`` is the only grader.
A finished attempt counts through ``record_puzzle_attempt``, and only the first run through
a puzzle does: the page sends ``record=false`` for retries after a miss or a reveal.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from .accounts import Viewer, require_access
from .db import session_scope
from .db_models import QuizAttemptRow, TrainingPositionRow
from .openings_api import _find_player
from .puzzles import (
    COACH_THEMES,
    THEME_LABELS,
    Puzzle,
    check_line,
    filter_puzzles,
    get_puzzle,
    load_puzzles,
    solution_sans,
)
from .repositories import get_or_create_player
from .training import record_puzzle_attempt

router = APIRouter(prefix="/api/puzzles")

MAX_PAGE_SIZE = 60
LICHESS_TRAINING_URL = "https://lichess.org/training/"
# Lichess tags that describe the puzzle's length or source, not an idea worth naming.
NOISE_TAGS = {"short", "long", "veryLong", "oneMove", "master", "masterVsMaster", "superGM"}


class PuzzleThemeOption(BaseModel):
    theme: str
    label: str
    count: int


class PuzzleCatalog(BaseModel):
    total: int
    min_rating: int | None = None
    max_rating: int | None = None
    themes: list[PuzzleThemeOption]


class PuzzleSummary(BaseModel):
    id: str
    fen: str
    rating: int
    theme: str
    theme_label: str
    # The player's latest result. Null for an unknown player or a puzzle they have not tried.
    status: Literal["solved", "failed"] | None = None


class PuzzlePage(BaseModel):
    total: int
    offset: int
    limit: int
    puzzles: list[PuzzleSummary]


class PuzzlePlayer(BaseModel):
    platform: str | None = None
    username: str | None = None
    record: bool = True
    elapsed_ms: int = Field(default=0, ge=0)


class PuzzleMoveRequest(PuzzlePlayer):
    line: list[str] = Field(min_length=1, max_length=64)


class PuzzleFinish(BaseModel):
    """Only sent once the puzzle is over, so a live puzzle never leaks its answer."""

    solution: list[str]
    solution_san: list[str]
    tags: list[str]
    url: str
    recorded: bool = False
    next_review_at: datetime | None = None
    streak: int | None = None


class PuzzleMoveResult(BaseModel):
    status: Literal["continue", "solved", "wrong"]
    reply: str | None = None
    finish: PuzzleFinish | None = None


def _finish(puzzle: Puzzle) -> PuzzleFinish:
    return PuzzleFinish(
        solution=list(puzzle.solution),
        solution_san=solution_sans(puzzle),
        tags=[tag for tag in puzzle.tags if tag not in NOISE_TAGS],
        url=f"{LICHESS_TRAINING_URL}{puzzle.id}",
    )


def _require(puzzle_id: str) -> Puzzle:
    puzzle = get_puzzle(puzzle_id)
    if puzzle is None:
        raise HTTPException(404, "Puzzle not found")
    return puzzle


def _record(
    request: PuzzlePlayer,
    puzzle: Puzzle,
    finish: PuzzleFinish,
    submitted: str,
    correct: bool,
    user_id: str | None,
) -> None:
    if not (request.record and request.platform and (request.username or "").strip()):
        return
    with session_scope() as session:
        require_access(session, request.platform, request.username, user_id)
        player = get_or_create_player(session, request.platform, request.username)
        schedule = record_puzzle_attempt(
            session, player, puzzle, submitted, correct, request.elapsed_ms
        )
        finish.recorded = True
        finish.next_review_at = schedule.due_at
        finish.streak = schedule.consecutive_successes


def _statuses(
    platform: str | None, username: str | None, ids: list[str], user_id: str | None
) -> dict[str, str]:
    if not platform or not username or not ids:
        return {}
    with session_scope() as session:
        require_access(session, platform, username, user_id)
        player = _find_player(session, platform, username)
        if player is None:
            return {}
        rows = session.execute(
            select(TrainingPositionRow.puzzle_id, QuizAttemptRow.correct)
            .join(QuizAttemptRow, QuizAttemptRow.position_id == TrainingPositionRow.id)
            .where(QuizAttemptRow.player_id == player.id, TrainingPositionRow.puzzle_id.in_(ids))
            .order_by(QuizAttemptRow.created_at)
        ).all()
    return {puzzle_id: "solved" if correct else "failed" for puzzle_id, correct in rows}


@router.get("/catalog", response_model=PuzzleCatalog)
def get_catalog() -> PuzzleCatalog:
    puzzles = load_puzzles()
    ratings = [item.rating for item in puzzles]
    return PuzzleCatalog(
        total=len(puzzles),
        min_rating=min(ratings, default=None),
        max_rating=max(ratings, default=None),
        themes=[
            PuzzleThemeOption(
                theme=theme,
                label=THEME_LABELS[theme],
                count=sum(item.theme == theme for item in puzzles),
            )
            for theme in COACH_THEMES
        ],
    )


@router.get("", response_model=PuzzlePage)
def list_puzzles(
    user_id: Viewer,
    theme: str | None = None,
    min_rating: int | None = Query(default=None, ge=0, le=4000),
    max_rating: int | None = Query(default=None, ge=0, le=4000),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=24, ge=1, le=MAX_PAGE_SIZE),
    platform: str | None = None,
    username: str | None = None,
) -> PuzzlePage:
    matches = filter_puzzles(theme, min_rating, max_rating)
    page = matches[offset : offset + limit]
    statuses = _statuses(platform, username, [item.id for item in page], user_id)
    return PuzzlePage(
        total=len(matches),
        offset=offset,
        limit=limit,
        puzzles=[
            PuzzleSummary(
                id=item.id,
                fen=item.fen,
                rating=item.rating,
                theme=item.theme,
                theme_label=THEME_LABELS.get(item.theme, item.theme),
                status=statuses.get(item.id),  # type: ignore[arg-type]
            )
            for item in page
        ],
    )


@router.post("/{puzzle_id}/moves", response_model=PuzzleMoveResult)
def submit_move(
    puzzle_id: str, request: PuzzleMoveRequest, user_id: Viewer
) -> PuzzleMoveResult:
    puzzle = _require(puzzle_id)
    try:
        check = check_line(puzzle, request.line)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if check.status == "continue":
        return PuzzleMoveResult(status="continue", reply=check.reply)
    finish = _finish(puzzle)
    _record(request, puzzle, finish, request.line[-1], check.status == "solved", user_id)
    return PuzzleMoveResult(status=check.status, finish=finish)


@router.post("/{puzzle_id}/reveal", response_model=PuzzleFinish)
def reveal_solution(puzzle_id: str, request: PuzzlePlayer, user_id: Viewer) -> PuzzleFinish:
    """Show the answer. Looking it up on a first run counts as a miss."""
    puzzle = _require(puzzle_id)
    finish = _finish(puzzle)
    _record(request, puzzle, finish, "revealed", False, user_id)
    return finish
