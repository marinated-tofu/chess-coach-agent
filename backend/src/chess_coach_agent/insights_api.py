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
    TimeSection,
    TimeSpent,
    LostOnTime,
    build_insights,
)
from .openings_api import _find_player

router = APIRouter(prefix="/api")

# (platform, normalized username, last) -> ((games, moments), response)
_CACHE: dict[tuple[str, str, int], tuple[tuple[int, int], InsightsResponse]] = {}
_CACHE_LOCK = threading.Lock()


def _empty(platform: str, username: str, last: int) -> InsightsResponse:
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
    )


@router.get("/insights/{platform}/{username}", response_model=InsightsResponse)
def get_insights(
    platform: str, username: str, last: int = Query(default=500, ge=1, le=3000)
) -> InsightsResponse:
    with session_scope() as session:
        player = _find_player(session, platform, username)
        if player is None:
            return _empty(platform, username, last)
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
        key = (platform, player.username_normalized, last)
        with _CACHE_LOCK:
            cached = _CACHE.get(key)
        if cached and cached[0] == (games, moments):
            return cached[1]
        response = build_insights(session, player, last, games)
        with _CACHE_LOCK:
            _CACHE[key] = ((games, moments), response)
        return response
