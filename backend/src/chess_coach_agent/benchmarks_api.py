"""GET /api/benchmarks/{platform}/{username}: peer comparisons (see benchmarks.py).

Separate from /api/insights so a slow Lichess call can't hold up the Insights page. Like
insights it reads public games only, so it is open for claimed players too.
"""

from __future__ import annotations

from fastapi import APIRouter

from .benchmarks import (
    LAST_GAMES,
    BenchmarksResponse,
    build_cohorts,
    lichess_percentiles,
    perfs_worth_checking,
)
from .db import session_scope
from .insights import _load_games
from .openings_api import _find_player

router = APIRouter(prefix="/api")


@router.get("/benchmarks/{platform}/{username}", response_model=BenchmarksResponse)
def get_benchmarks(platform: str, username: str) -> BenchmarksResponse:
    # Pasted PGNs have no shared rating scale, so only the two sites are compared.
    if platform not in ("chess.com", "lichess"):
        return BenchmarksResponse(platform=platform, username=username)
    with session_scope() as session:
        player = _find_player(session, platform, username)
        if player is None:
            return BenchmarksResponse(platform=platform, username=username)
        handle = player.username
        games = _load_games(session, player.id, LAST_GAMES)
        cohorts = build_cohorts(session, player, games)
    # Outside the session: no database connection is held while waiting on Lichess.
    percentiles = lichess_percentiles(handle, perfs_worth_checking(games)) if platform == "lichess" else []
    return BenchmarksResponse(
        platform=platform, username=handle, rating_percentiles=percentiles, cohorts=cohorts
    )
