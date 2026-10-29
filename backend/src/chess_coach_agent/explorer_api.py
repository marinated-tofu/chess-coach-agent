"""HTTP routes for the opening explorer (/api/explorer)."""

from __future__ import annotations

import threading
import time

import chess
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from .db import session_scope
from .db_models import GameRow, PlayerRow
from .explorer import (
    ColorFilter,
    ExplorerUnavailable,
    GameSummary,
    LichessDb,
    PositionIndex,
    build_position_index,
    fetch_lichess,
    opening_for_fen,
    query_player_index,
)
from .repositories import normalize_username

router = APIRouter(prefix="/api/explorer")

# Re-analysis rewrites stored moves without changing the game count, so cached
# indexes also expire after a while.
INDEX_TTL_SECONDS = 600

# (platform, username) -> (game count, built at, index)
_INDEXES: dict[tuple[str, str], tuple[int, float, PositionIndex]] = {}
_INDEX_LOCK = threading.Lock()
_BUILD_LOCKS: dict[tuple[str, str], threading.Lock] = {}


def _valid_fen(fen: str) -> str:
    fen = fen.strip()
    try:
        chess.Board(fen)
    except ValueError as exc:
        raise HTTPException(422, "Invalid FEN.") from exc
    return fen


def clear_index_cache() -> None:
    with _INDEX_LOCK:
        _INDEXES.clear()


def _player_index(platform: str, username: str) -> PositionIndex | None:
    key = (platform, normalize_username(username))
    with session_scope() as session:
        player_id = session.scalar(
            select(PlayerRow.id).where(
                PlayerRow.platform == platform, PlayerRow.username_normalized == key[1]
            )
        )
        if player_id is None:
            return None
        count = (
            session.scalar(
                select(func.count()).select_from(GameRow).where(GameRow.player_id == player_id)
            )
            or 0
        )
        with _INDEX_LOCK:
            cached = _INDEXES.get(key)
            build_lock = _BUILD_LOCKS.setdefault(key, threading.Lock())
        if cached and cached[0] == count and time.monotonic() - cached[1] < INDEX_TTL_SECONDS:
            return cached[2]
        with build_lock:
            # Another request may have built it while we waited.
            with _INDEX_LOCK:
                cached = _INDEXES.get(key)
            if cached and cached[0] == count and time.monotonic() - cached[1] < INDEX_TTL_SECONDS:
                return cached[2]
            rows = session.execute(
                select(
                    GameRow.player_color,
                    GameRow.player_result,
                    GameRow.played_at,
                    GameRow.metadata_json,
                ).where(GameRow.player_id == player_id)
            ).all()
            games = [
                GameSummary(
                    color=color,
                    result=result,
                    played_at=played_at or "",
                    moves=(stored or {}).get("moves", []),
                )
                for color, result, played_at, stored in rows
            ]
            index = build_position_index(games)
            with _INDEX_LOCK:
                _INDEXES[key] = (count, time.monotonic(), index)
            return index


@router.get("/player")
def player_explorer(
    platform: str = Query(...),
    username: str = Query(...),
    fen: str = Query(default=chess.STARTING_FEN),
    color: ColorFilter = Query(default="both"),
) -> dict:
    fen = _valid_fen(fen)
    index = _player_index(platform, username)
    if index is None:
        return {
            "fen": fen,
            "color": color,
            "total": 0,
            "opening": opening_for_fen(fen),
            "moves": [],
            "common_mistake": None,
        }
    return query_player_index(index, fen, color)


@router.get("/lichess")
def lichess_explorer(
    fen: str = Query(default=chess.STARTING_FEN),
    db: LichessDb = Query(default="lichess"),
    ratings: str = Query(default="", pattern=r"^[0-9,]{0,60}$"),
    speeds: str = Query(default="", pattern=r"^[a-z,]{0,80}$"),
):
    fen = _valid_fen(fen)
    try:
        return fetch_lichess(fen, db, ratings=ratings, speeds=speeds)
    except ExplorerUnavailable as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
