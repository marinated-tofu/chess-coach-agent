"""GET /api/today/{platform}/{username}: what the Today page needs in one read-only call.

Counts come from the database, never from a browser cache, so the library size shown in the
app does not drop to whatever the client happened to keep in storage. Ratings are read from the
latest game of each time control, which keeps them stable across reloads (``PlayerRow``'s single
``current_rating`` is overwritten by whichever game a sync batch stored last).
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .accounts import Viewer, can_access
from .db import session_scope
from .db_models import GameRow, ReviewScheduleRow, SyncJobRow, TrainingPositionRow
from .insights import time_category
from .library_api import player_index
from .openings_api import _find_player
from .repositories import load_analyses

router = APIRouter(prefix="/api")
_TRAILING_DIGITS = re.compile(r"(\d+)/?$")


class ThemeCount(BaseModel):
    theme: str
    count: int


class DueSummary(BaseModel):
    count: int = 0
    themes: list[ThemeCount] = Field(default_factory=list)
    next_due_at: datetime | None = None


class FirstMoment(BaseModel):
    id: str
    ply: int
    move_number: int
    fen_before: str
    played_san: str
    best_san: str | None = None
    theme: str
    judgment: str


class LatestGame(BaseModel):
    game_id: str
    white: str
    black: str
    opponent: str
    player_color: str
    player_result: str
    date: str
    time_control: str
    time_category: str | None = None
    accuracy: float | None = None
    blunders: int = 0
    mistakes: int = 0
    first_moment: FirstMoment | None = None


class TodaySummary(BaseModel):
    platform: str
    username: str
    known: bool = False
    total_games: int = 0
    # Latest rating per time control ("bullet" | "blitz" | "rapid" | "daily").
    current_rating: dict[str, int] = Field(default_factory=dict)
    last_synced_at: datetime | None = None
    due: DueSummary = Field(default_factory=DueSummary)
    # True when due reviews were left out because the viewer does not own this player.
    private: bool = False
    latest_game: LatestGame | None = None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _dated():
    # Unknown PGN dates ("????.??.??") sort after digits, so keep only real dates.
    return GameRow.played_at >= "0", GameRow.played_at < ":"


def _link_number(link: str) -> int:
    # Chess.com game ids grow over time; PGN dates have no time of day, so they order same-day games.
    match = _TRAILING_DIGITS.search(link or "")
    return int(match.group(1)) if match else -1


def _recency(played_at: str, link: str, created_at: datetime) -> tuple[str, int, datetime]:
    return played_at, _link_number(link), _aware(created_at)


def _ratings(session: Session, player_id: str) -> dict[str, int]:
    rows = session.execute(
        select(
            GameRow.played_at, GameRow.link, GameRow.created_at, GameRow.time_control, GameRow.player_elo
        ).where(GameRow.player_id == player_id, GameRow.player_elo.is_not(None), *_dated())
    ).all()
    rows.sort(key=lambda row: _recency(row[0], row[1], row[2]), reverse=True)
    ratings: dict[str, int] = {}
    for _played, _link, _created, time_control, elo in rows:
        category = time_category(time_control or "")
        if category and category not in ratings:
            ratings[category] = int(elo)
            if len(ratings) == 4:
                break
    return ratings


def _due(session: Session, player_id: str, now: datetime) -> DueSummary:
    rows = session.execute(
        select(ReviewScheduleRow.due_at, TrainingPositionRow.theme)
        .join(TrainingPositionRow, TrainingPositionRow.id == ReviewScheduleRow.position_id)
        .where(ReviewScheduleRow.player_id == player_id)
    ).all()
    due_themes: Counter[str] = Counter()
    upcoming: list[datetime] = []
    for due_at, theme in rows:
        when = _aware(due_at)
        if when <= now:
            due_themes[theme] += 1
        else:
            upcoming.append(when)
    return DueSummary(
        count=sum(due_themes.values()),
        themes=[ThemeCount(theme=name, count=count) for name, count in due_themes.most_common()],
        next_due_at=min(upcoming) if upcoming else None,
    )


def _latest_game(session: Session, platform: str, username: str, player_id: str) -> LatestGame | None:
    latest_date = session.scalar(
        select(func.max(GameRow.played_at)).where(GameRow.player_id == player_id, *_dated())
    )
    if latest_date is None:
        return None
    same_day = session.scalars(
        select(GameRow).where(GameRow.player_id == player_id, GameRow.played_at == latest_date)
    ).all()
    row = max(same_day, key=lambda game: _recency(game.played_at, game.link, game.created_at))
    loaded = load_analyses(session, platform, username, row.external_game_id).analyses
    analysis = loaded[0] if loaded else None
    color = row.player_color
    opponent = row.black if color == "white" else row.white
    accuracy = None
    moments = []
    if analysis is not None:
        if analysis.accuracy is not None and color in ("white", "black"):
            accuracy = getattr(analysis.accuracy, color)
        moments = sorted(analysis.moments, key=lambda item: item.ply)
    first = moments[0] if moments else None
    return LatestGame(
        game_id=row.external_game_id,
        white=row.white,
        black=row.black,
        opponent=opponent,
        player_color=color,
        player_result=row.player_result,
        date=row.played_at,
        time_control=row.time_control,
        time_category=time_category(row.time_control or ""),
        accuracy=round(accuracy, 1) if accuracy is not None else None,
        blunders=sum(1 for item in moments if item.judgment == "blunder"),
        mistakes=sum(1 for item in moments if item.judgment == "mistake"),
        first_moment=FirstMoment(
            id=first.id,
            ply=first.ply,
            move_number=first.move_number,
            fen_before=first.fen_before,
            played_san=first.played_san,
            best_san=first.best_san,
            theme=first.theme,
            judgment=first.judgment,
        )
        if first
        else None,
    )


def today_summary(session: Session, platform: str, username: str) -> TodaySummary:
    player = _find_player(session, platform, username)
    if player is None:
        return TodaySummary(platform=platform, username=username)
    # Same count as the games library, which hides empty "? vs ?" rows.
    total = len(player_index(session, player).games)
    synced = session.scalar(
        select(SyncJobRow.updated_at)
        .where(SyncJobRow.player_id == player.id, SyncJobRow.status == "complete")
        .order_by(SyncJobRow.updated_at.desc())
        .limit(1)
    )
    return TodaySummary(
        platform=platform,
        username=player.username,
        known=True,
        total_games=total,
        current_rating=_ratings(session, player.id),
        last_synced_at=_aware(synced) if synced else None,
        due=_due(session, player.id, datetime.now(UTC)),
        latest_game=_latest_game(session, platform, username, player.id),
    )


@router.get("/today/{platform}/{username}", response_model=TodaySummary)
def get_today(platform: str, username: str, user_id: Viewer) -> TodaySummary:
    with session_scope() as session:
        summary = today_summary(session, platform, username)
        if can_access(session, platform, username, user_id):
            return summary
        return summary.model_copy(update={"due": DueSummary(), "private": True})
