"""Game library summaries, paginated and filtered, plus the aggregates Progress and Practice show.

``GET /api/games/{platform}/{username}`` returns every stored analysis with its moves and FENs,
which is about 75 MB for a 3,000-game history. The library only needs one line per game, so
these endpoints read light columns into a per-player index, filter and page it in memory, and
load the heavy ``metadata_json`` only for the rows on the requested page.

Junk rows are hidden everywhere here: a game with no named players (``?`` vs ``?``) or with
no moves cannot be reviewed, so it never appears in the library or in its counts.
"""

from __future__ import annotations

import re
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .classification import game_accuracy
from .accounts import Viewer, can_access
from .db import session_scope
from .db_models import CriticalMomentRow, GameRow, PlayerRow, ReviewScheduleRow, TrainingPositionRow
from .insights import time_category
from .openings import classify_moves, opening_book
from .repositories import normalize_username

router = APIRouter(prefix="/api/library")

TimeClass = Literal["bullet", "blitz", "rapid", "daily"]
TIME_CLASSES: tuple[str, ...] = ("bullet", "blitz", "rapid", "daily")
UNKNOWN_NAMES = {"", "?"}
_TRAILING_DIGITS = re.compile(r"(\d+)/?$")
_DATE = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2})$")


# ---------------------------------------------------------------- response models


class LibraryGame(BaseModel):
    game_id: str
    date: str = Field(description="ISO date (YYYY-MM-DD), or empty when the PGN has none")
    white: str
    black: str
    opponent: str
    player_color: str
    player_result: str
    result: str
    player_elo: int | None = None
    opponent_elo: int | None = None
    time_control: str = ""
    time_class: str | None = None
    opening: str | None = None
    opening_family: str | None = None
    eco: str = ""
    move_count: int = 0
    moment_count: int = 0
    blunders: int = 0
    mistakes: int = 0
    top_themes: list[str] = Field(default_factory=list)
    accuracy: float | None = None
    link: str = ""


class FacetCount(BaseModel):
    name: str
    count: int


class LibraryFacets(BaseModel):
    results: dict[str, int] = Field(default_factory=dict)
    colors: dict[str, int] = Field(default_factory=dict)
    time_classes: dict[str, int] = Field(default_factory=dict)
    openings: list[FacetCount] = Field(default_factory=list)
    openings_ready: bool = False


class LibraryPage(BaseModel):
    platform: str
    username: str
    library_total: int = Field(description="Reviewable games in the library, before filters")
    total: int = Field(description="Games matching the filters")
    offset: int
    limit: int
    has_more: bool
    items: list[LibraryGame]
    facets: LibraryFacets


class RatingPoint(BaseModel):
    date: str
    rating: int


class Blindspot(BaseModel):
    theme: str
    games: int
    moments: int
    pct_of_games: float


class LibraryProgress(BaseModel):
    platform: str
    username: str
    total_games: int
    rating_series: dict[str, list[RatingPoint]] = Field(default_factory=dict)
    blindspots: list[Blindspot] = Field(default_factory=list)


class QueuePreview(BaseModel):
    moment_id: str
    game_id: str
    fen: str
    theme: str
    judgment: str
    played_san: str
    move_number: int
    opponent: str
    date: str


class PracticeQueue(BaseModel):
    platform: str
    username: str
    due_count: int = 0
    due_themes: list[FacetCount] = Field(default_factory=list)
    next_due_at: datetime | None = None
    candidate_count: int = 0
    candidate_themes: list[FacetCount] = Field(default_factory=list)
    preview: QueuePreview | None = None


# ---------------------------------------------------------------- per-player index


@dataclass
class _Game:
    row_id: str
    game_id: str
    white: str
    black: str
    result: str
    player_result: str
    color: str
    elo: int | None
    played_at: str
    time_control: str
    time_class: str | None
    link: str
    created_at: datetime
    move_count: int
    moments: int = 0
    blunders: int = 0
    mistakes: int = 0
    themes: Counter[str] = field(default_factory=Counter)

    @property
    def opponent(self) -> str:
        return self.black if self.color == "white" else self.white if self.color == "black" else ""

    @property
    def junk(self) -> bool:
        no_players = self.white.strip() in UNKNOWN_NAMES and self.black.strip() in UNKNOWN_NAMES
        return no_players or self.move_count == 0

    def recency(self) -> tuple[int, str, int, datetime]:
        dated = 1 if _DATE.match(self.played_at or "") else 0
        return dated, self.played_at, _link_number(self.link), _aware(self.created_at)


@dataclass
class _Index:
    signature: tuple[int, int]
    games: list[_Game]  # reviewable games only, newest first
    # row id -> (eco, full name, family), filled in the background
    openings: dict[str, tuple[str, str, str]] | None = None


_INDEX: dict[str, _Index] = {}
_LOCK = threading.Lock()
_OPENING_JOBS: set[str] = set()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _link_number(link: str) -> int:
    match = _TRAILING_DIGITS.search(link or "")
    return int(match.group(1)) if match else -1


def iso_date(played_at: str) -> str:
    match = _DATE.match(played_at or "")
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}" if match else ""


def _find_player(session: Session, platform: str, username: str) -> PlayerRow | None:
    return session.scalar(
        select(PlayerRow).where(
            PlayerRow.platform == platform,
            PlayerRow.username_normalized == normalize_username(username),
        )
    )


def _signature(session: Session, player_id: str) -> tuple[int, int]:
    games = (
        session.scalar(select(func.count()).select_from(GameRow).where(GameRow.player_id == player_id))
        or 0
    )
    moments = (
        session.scalar(
            select(func.count())
            .select_from(CriticalMomentRow)
            .join(GameRow, GameRow.id == CriticalMomentRow.game_id)
            .where(GameRow.player_id == player_id)
        )
        or 0
    )
    return games, moments


def _move_counts(session: Session, player_id: str) -> dict[str, int]:
    if session.get_bind().dialect.name == "sqlite":
        rows = session.execute(
            select(GameRow.id, func.json_array_length(GameRow.metadata_json, "$.moves")).where(
                GameRow.player_id == player_id
            )
        ).all()
        return {row_id: int(count or 0) for row_id, count in rows}
    rows = session.execute(
        select(GameRow.id, GameRow.metadata_json).where(GameRow.player_id == player_id)
    ).all()
    return {row_id: len((stored or {}).get("moves", [])) for row_id, stored in rows}


def _build_index(session: Session, player_id: str, signature: tuple[int, int]) -> _Index:
    move_counts = _move_counts(session, player_id)
    rows = session.execute(
        select(
            GameRow.id,
            GameRow.external_game_id,
            GameRow.white,
            GameRow.black,
            GameRow.result,
            GameRow.player_result,
            GameRow.player_color,
            GameRow.player_elo,
            GameRow.played_at,
            GameRow.time_control,
            GameRow.link,
            GameRow.created_at,
        ).where(GameRow.player_id == player_id)
    ).all()
    games: dict[str, _Game] = {}
    for row in rows:
        games[row[0]] = _Game(
            row_id=row[0],
            game_id=row[1],
            white=row[2] or "",
            black=row[3] or "",
            result=row[4] or "",
            player_result=row[5] or "",
            color=row[6] or "",
            elo=row[7],
            played_at=row[8] or "",
            time_control=row[9] or "",
            time_class=time_category(row[9] or ""),
            link=row[10] or "",
            created_at=row[11],
            move_count=move_counts.get(row[0], 0),
        )
    moments = session.execute(
        select(CriticalMomentRow.game_id, CriticalMomentRow.theme, CriticalMomentRow.explanation)
        .join(GameRow, GameRow.id == CriticalMomentRow.game_id)
        .where(GameRow.player_id == player_id)
    ).all()
    for game_row_id, theme, explanation in moments:
        game = games.get(game_row_id)
        if game is None:
            continue
        game.moments += 1
        game.themes[theme] += 1
        judgment = (explanation or {}).get("judgment")
        if judgment == "blunder":
            game.blunders += 1
        elif judgment == "mistake":
            game.mistakes += 1
    kept = [game for game in games.values() if not game.junk]
    kept.sort(key=lambda game: game.recency(), reverse=True)
    return _Index(signature=signature, games=kept)


def _classify_openings(player_id: str, key: str, signature: tuple[int, int]) -> None:
    """Name the opening of every game (needs each game's moves), then attach it to the index."""
    try:
        opening_book()
        found: dict[str, tuple[str, str, str]] = {}
        with session_scope() as session:
            result = session.execute(
                select(GameRow.id, GameRow.metadata_json)
                .where(GameRow.player_id == player_id)
                .execution_options(yield_per=200)
            )
            for row_id, stored in result:
                match = classify_moves((stored or {}).get("moves", []))
                if match is not None:
                    found[row_id] = (match.opening.eco, match.opening.name, match.opening.family)
        with _LOCK:
            index = _INDEX.get(key)
            if index is not None and index.signature == signature:
                index.openings = found
    finally:
        with _LOCK:
            _OPENING_JOBS.discard(key)


def _start_opening_job(player_id: str, key: str, signature: tuple[int, int]) -> None:
    with _LOCK:
        if key in _OPENING_JOBS:
            return
        _OPENING_JOBS.add(key)
    threading.Thread(
        target=_classify_openings, args=(player_id, key, signature), name="library-openings", daemon=True
    ).start()


def player_index(session: Session, player: PlayerRow, wait_for_openings: bool = False) -> _Index:
    key = player.id
    signature = _signature(session, player.id)
    with _LOCK:
        index = _INDEX.get(key)
    if index is None or index.signature != signature:
        index = _build_index(session, player.id, signature)
        with _LOCK:
            _INDEX[key] = index
    if index.openings is None:
        if wait_for_openings:
            _classify_openings_now(player.id, key, signature)
        else:
            _start_opening_job(player.id, key, signature)
    return index


def _classify_openings_now(player_id: str, key: str, signature: tuple[int, int]) -> None:
    with _LOCK:
        _OPENING_JOBS.add(key)
    _classify_openings(player_id, key, signature)


def _warm_all() -> None:
    try:
        with session_scope() as session:
            for player in session.scalars(select(PlayerRow)).all():
                player_index(session, player)
    except Exception:  # noqa: BLE001 - warming is best effort; requests build the index anyway
        pass


# ---------------------------------------------------------------- library page


def _page_details(session: Session, games: list[_Game]) -> dict[str, dict[str, Any]]:
    """Opening, accuracy and opponent rating for the rows on one page."""
    if not games:
        return {}
    rows = session.execute(
        select(GameRow.id, GameRow.metadata_json).where(GameRow.id.in_([game.row_id for game in games]))
    ).all()
    colors = {game.row_id: game.color for game in games}
    details: dict[str, dict[str, Any]] = {}
    for row_id, stored in rows:
        stored = stored or {}
        payload = stored.get("game", stored)
        moves = stored.get("moves", [])
        match = classify_moves(moves)
        accuracy = None
        color = colors.get(row_id)
        win_pcts = [move.get("win_pct") for move in moves]
        if color in ("white", "black") and win_pcts and all(isinstance(v, (int, float)) for v in win_pcts):
            accuracy = game_accuracy(win_pcts, white_moves_first=moves[0].get("color", "white") == "white")[
                color
            ]
        details[row_id] = {
            "eco": (match.opening.eco if match else None) or payload.get("eco", "") or "",
            "opening": match.opening.name if match else None,
            "opening_family": match.opening.family if match else None,
            "opponent_elo": payload.get("opponent_elo"),
            "accuracy": accuracy,
        }
    return details


def _summary(game: _Game, detail: dict[str, Any]) -> LibraryGame:
    return LibraryGame(
        game_id=game.game_id,
        date=iso_date(game.played_at),
        white=game.white,
        black=game.black,
        opponent=game.opponent,
        player_color=game.color,
        player_result=game.player_result,
        result=game.result,
        player_elo=game.elo,
        opponent_elo=detail.get("opponent_elo"),
        time_control=game.time_control,
        time_class=game.time_class,
        opening=detail.get("opening"),
        opening_family=detail.get("opening_family"),
        eco=detail.get("eco", ""),
        move_count=(game.move_count + 1) // 2,
        moment_count=game.moments,
        blunders=game.blunders,
        mistakes=game.mistakes,
        top_themes=[theme for theme, _ in game.themes.most_common(3)],
        accuracy=detail.get("accuracy"),
        link=game.link,
    )


def _facets(index: _Index) -> LibraryFacets:
    openings: list[FacetCount] = []
    if index.openings is not None:
        families = Counter(
            index.openings[game.row_id][2] for game in index.games if game.row_id in index.openings
        )
        openings = [FacetCount(name=name, count=count) for name, count in families.most_common(40)]
    return LibraryFacets(
        results=dict(Counter(game.player_result for game in index.games)),
        colors=dict(Counter(game.color for game in index.games)),
        time_classes=dict(Counter(game.time_class for game in index.games if game.time_class)),
        openings=openings,
        openings_ready=index.openings is not None,
    )


def library_page(
    session: Session,
    platform: str,
    username: str,
    *,
    offset: int = 0,
    limit: int = 50,
    result: str | None = None,
    color: str | None = None,
    time_class: str | None = None,
    opening: str | None = None,
    q: str | None = None,
    sort: str = "date",
    theme: str | None = None,
) -> LibraryPage:
    player = _find_player(session, platform, username)
    if player is None:
        return LibraryPage(
            platform=platform,
            username=username,
            library_total=0,
            total=0,
            offset=offset,
            limit=limit,
            has_more=False,
            items=[],
            facets=LibraryFacets(openings_ready=True),
        )
    index = player_index(session, player, wait_for_openings=bool(opening))
    games = index.games
    if result:
        games = [game for game in games if game.player_result == result]
    if color:
        games = [game for game in games if game.color == color]
    if time_class:
        games = [game for game in games if game.time_class == time_class]
    if opening and index.openings is not None:
        names = index.openings
        games = [game for game in games if game.row_id in names and names[game.row_id][2] == opening]
    if theme:
        games = [game for game in games if game.themes.get(theme)]
    if q and q.strip():
        needle = q.strip().casefold()
        games = [game for game in games if needle in game.opponent.casefold()]
    if sort == "blunders":
        games = sorted(games, key=lambda game: (game.blunders, game.mistakes, game.recency()), reverse=True)
    page = games[offset : offset + limit]
    details = _page_details(session, page)
    return LibraryPage(
        platform=platform,
        username=player.username,
        library_total=len(index.games),
        total=len(games),
        offset=offset,
        limit=limit,
        has_more=offset + len(page) < len(games),
        items=[_summary(game, details.get(game.row_id, {})) for game in page],
        facets=_facets(index),
    )


# ---------------------------------------------------------------- progress aggregates


def library_progress(session: Session, platform: str, username: str) -> LibraryProgress:
    player = _find_player(session, platform, username)
    if player is None:
        return LibraryProgress(platform=platform, username=username, total_games=0)
    index = player_index(session, player)
    # One point per day per time control: the rating after the last game that day.
    daily: dict[str, dict[str, int]] = defaultdict(dict)
    for game in reversed(index.games):  # oldest first, so later games overwrite the day
        day = iso_date(game.played_at)
        if game.elo is None or not day or game.time_class is None:
            continue
        daily[game.time_class][day] = int(game.elo)
    series = {
        name: [RatingPoint(date=day, rating=rating) for day, rating in sorted(points.items())]
        for name, points in daily.items()
        if points
    }
    total = len(index.games)
    games_with: Counter[str] = Counter()
    moments: Counter[str] = Counter()
    for game in index.games:
        for theme, count in game.themes.items():
            games_with[theme] += 1
            moments[theme] += count
    blindspots = [
        Blindspot(
            theme=theme,
            games=count,
            moments=moments[theme],
            pct_of_games=round(count / total * 100, 1) if total else 0.0,
        )
        for theme, count in games_with.most_common()
    ]
    return LibraryProgress(
        platform=platform,
        username=player.username,
        total_games=total,
        rating_series=series,
        blindspots=blindspots,
    )


# ---------------------------------------------------------------- practice queue


def practice_queue(session: Session, platform: str, username: str) -> PracticeQueue:
    player = _find_player(session, platform, username)
    if player is None:
        return PracticeQueue(platform=platform, username=username)
    now = datetime.now(UTC)
    due_rows = session.execute(
        select(ReviewScheduleRow.due_at, TrainingPositionRow.theme)
        .join(TrainingPositionRow, TrainingPositionRow.id == ReviewScheduleRow.position_id)
        .where(ReviewScheduleRow.player_id == player.id)
    ).all()
    due_themes: Counter[str] = Counter()
    upcoming: list[datetime] = []
    for due_at, theme in due_rows:
        when = _aware(due_at)
        if when <= now:
            due_themes[theme] += 1
        else:
            upcoming.append(when)

    # Same ordering as a new practice session: trainable moments by severity, highest first.
    candidates = session.execute(
        select(
            CriticalMomentRow.external_moment_id,
            CriticalMomentRow.theme,
            CriticalMomentRow.fen_before,
            CriticalMomentRow.played_san,
            CriticalMomentRow.move_number,
            CriticalMomentRow.explanation,
            GameRow.external_game_id,
            GameRow.white,
            GameRow.black,
            GameRow.player_color,
            GameRow.played_at,
        )
        .join(GameRow, CriticalMomentRow.game_id == GameRow.id)
        .where(GameRow.player_id == player.id, CriticalMomentRow.best_san.is_not(None))
        .order_by(CriticalMomentRow.severity.desc())
    ).all()
    trainable = [row for row in candidates if (row.explanation or {}).get("trainable", False)]
    pool = trainable or candidates
    first = pool[0] if pool else None
    preview = None
    if first is not None:
        opponent = first.black if first.player_color == "white" else first.white
        preview = QueuePreview(
            moment_id=first.external_moment_id,
            game_id=first.external_game_id,
            fen=first.fen_before,
            theme=first.theme,
            judgment=(first.explanation or {}).get("judgment", "mistake"),
            played_san=first.played_san,
            move_number=first.move_number,
            opponent=opponent,
            date=iso_date(first.played_at),
        )
    themes = Counter(row.theme for row in pool)
    return PracticeQueue(
        platform=platform,
        username=player.username,
        due_count=sum(due_themes.values()),
        due_themes=[FacetCount(name=name, count=count) for name, count in due_themes.most_common()],
        next_due_at=min(upcoming) if upcoming else None,
        candidate_count=len(pool),
        candidate_themes=[FacetCount(name=name, count=count) for name, count in themes.most_common(6)],
        preview=preview,
    )


# ---------------------------------------------------------------- opening positions


class OpeningPosition(BaseModel):
    name: str
    eco: str
    fen: str
    ply: int


def opening_position(name: str) -> OpeningPosition | None:
    """The book position that names an opening (or the shallowest one of its family)."""
    wanted = name.strip().casefold()
    best: tuple[int, str, str, str] | None = None
    for epd, opening in opening_book().items():
        exact = opening.name.casefold() == wanted
        if not exact and opening.family.casefold() != wanted:
            continue
        rank = (0 if exact else 1) * 1000 + opening.ply
        if best is None or rank < best[0]:
            best = (rank, epd, opening.name, opening.eco)
    if best is None:
        return None
    _rank, epd, found_name, eco = best
    return OpeningPosition(name=found_name, eco=eco, fen=f"{epd} 0 1", ply=_rank % 1000)


# ---------------------------------------------------------------- routes


@router.get("/opening-position", response_model=OpeningPosition)
def get_opening_position(name: str = Query(min_length=1, max_length=120)) -> OpeningPosition:
    found = opening_position(name)
    if found is None:
        raise HTTPException(404, "No book position for that opening")
    return found



@router.get("/{platform}/{username}", response_model=LibraryPage)
def get_library(
    platform: str,
    username: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    result: Literal["win", "loss", "draw"] | None = None,
    color: Literal["white", "black"] | None = None,
    time_class: TimeClass | None = None,
    opening: str | None = Query(default=None, max_length=120),
    q: str | None = Query(default=None, max_length=100),
    sort: Literal["date", "blunders"] = "date",
    theme: str | None = Query(default=None, max_length=40),
) -> LibraryPage:
    with session_scope() as session:
        return library_page(
            session,
            platform,
            username,
            offset=offset,
            limit=limit,
            result=result,
            color=color,
            time_class=time_class,
            opening=opening,
            q=q,
            sort=sort,
            theme=theme,
        )


@router.get("/{platform}/{username}/progress", response_model=LibraryProgress)
def get_library_progress(platform: str, username: str) -> LibraryProgress:
    with session_scope() as session:
        return library_progress(session, platform, username)


@router.get("/{platform}/{username}/practice-queue", response_model=PracticeQueue)
def get_practice_queue(platform: str, username: str, user_id: Viewer) -> PracticeQueue:
    with session_scope() as session:
        queue = practice_queue(session, platform, username)
        if can_access(session, platform, username, user_id):
            return queue
        # The candidates come from public games; the review schedule is the player's own.
        return queue.model_copy(update={"due_count": 0, "due_themes": [], "next_due_at": None})


# Build indexes in the background so the first library request after a restart is fast.
threading.Thread(target=_warm_all, name="library-warmup", daemon=True).start()
