"""GET /api/insights/{platform}/{username}: where the player loses games (see insights.py)."""

from __future__ import annotations

import threading

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from .db import session_scope
from .db_models import CriticalMomentRow, GameRow
from .insights import (
    ColorSection,
    ConversionSection,
    InsightsResponse,
    OpponentSection,
    PhaseSection,
    ScheduleBreakdown,
    ScheduleSection,
    TimeSection,
    TimeSpent,
    LostOnTime,
    build_insights,
    resolve_timezone,
)
from .openings_api import _find_player

router = APIRouter(prefix="/api")

# (platform, normalized username, last, timezone) -> ((games, moments, dated games), response)
_CACHE: dict[tuple[str, str, int, str], tuple[tuple[int, int, int], InsightsResponse]] = {}
_CACHE_LOCK = threading.Lock()


def _empty(platform: str, username: str, last: int, timezone: str) -> InsightsResponse:
    return InsightsResponse(
        platform=platform,
        username=username,
        last=last,
        total_games=0,
        games_considered=0,
        engine_games=0,
        clock_games=0,
        phases=PhaseSection(sample_size=0, accuracy_sample_size=0, rows=[]),
        time=TimeSection(
            sample_size=0,
            by_control=[],
            by_control_sample_size=0,
            pressure=[],
            time_spent=TimeSpent(sample_size=0),
            lost_on_time=LostOnTime(sample_size=0),
        ),
        opponents=OpponentSection(sample_size=0, rows=[]),
        colors=ColorSection(sample_size=0, accuracy_sample_size=0, rows=[]),
        conversion=ConversionSection(sample_size=0),
        schedule=ScheduleSection(
            sample_size=0,
            undated_games=0,
            timezone=timezone,
            by_time_of_day=ScheduleBreakdown(rows=[]),
            by_day_of_week=ScheduleBreakdown(rows=[]),
        ),
    )


@router.get("/insights/{platform}/{username}", response_model=InsightsResponse)
def get_insights(
    platform: str,
    username: str,
    last: int = Query(default=500, ge=1, le=3000),
    tz: str | None = Query(default=None, max_length=64, description="IANA timezone, e.g. Asia/Manila"),
) -> InsightsResponse:
    timezone = resolve_timezone(tz)[1]
    with session_scope() as session:
        player = _find_player(session, platform, username)
        if player is None:
            return _empty(platform, username, last, timezone)
        games = (
            session.scalar(
                select(func.count()).select_from(GameRow).where(GameRow.player_id == player.id)
            )
            or 0
        )
        moments = (
            session.scalar(
                select(func.count())
                .select_from(CriticalMomentRow)
                .join(GameRow, GameRow.id == CriticalMomentRow.game_id)
                .where(GameRow.player_id == player.id)
            )
            or 0
        )
        # A sync can add start times to existing games without changing the other counts.
        dated = (
            session.scalar(
                select(func.count())
                .select_from(GameRow)
                .where(GameRow.player_id == player.id, GameRow.started_at.is_not(None))
            )
            or 0
        )
        key = (platform, player.username_normalized, last, timezone)
        with _CACHE_LOCK:
            cached = _CACHE.get(key)
        if cached and cached[0] == (games, moments, dated):
            return cached[1]
        response = build_insights(session, player, last, games, timezone)
        with _CACHE_LOCK:
            _CACHE[key] = ((games, moments, dated), response)
        return response
