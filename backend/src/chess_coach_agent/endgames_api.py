"""Endgame trainer routes: the drill list and one engine turn (model documented in endgames.py)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import chess
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .accounts import Viewer, require_access
from .db import session_scope
from .db_models import PlayerRow
from .endgames import (
    ENGINE_DEPTH,
    ENGINE_MAX_NODES,
    GAME_DRILL_PREFIX,
    Drill,
    DrillProgress,
    Turn,
    drill_progress,
    get_essential,
    get_game_drill,
    load_essentials,
    own_game_drills,
    play_turn,
    record_result,
)
from .engine import EngineAnalyzer
from .engine_api import engine_binary
from .monitoring import log_event
from .repositories import get_or_create_player, normalize_username

router = APIRouter(prefix="/api/endgames")


class DrillOut(BaseModel):
    id: str
    kind: str  # essential | game
    title: str
    category: str
    fen: str
    player_color: str
    goal: str  # win | draw
    finish: str  # engine | mate
    move_limit: int
    summary: str
    hint: str
    game_id: str | None = None
    opponent: str | None = None
    played_at: str | None = None
    played_san: str | None = None
    move_number: int | None = None
    attempts: int = 0
    passes: int = 0
    last_passed: bool | None = None
    due_at: datetime | None = None
    due: bool = False


class DrillsResponse(BaseModel):
    drills: list[DrillOut]


class TurnRequest(BaseModel):
    drill_id: str
    moves_uci: list[str] = Field(default_factory=list)  # the whole line from the drill's start
    strikes: int = Field(default=0, ge=0)
    resign: bool = False
    hints_used: int = Field(default=0, ge=0)
    elapsed_ms: int = Field(default=0, ge=0)
    platform: str | None = None
    username: str | None = None


class TurnOut(BaseModel):
    status: str  # playing | passed | failed
    result: str
    reason: str
    fen: str
    reply_san: str | None = None
    reply_uci: str | None = None
    strikes: int = 0
    recorded: bool = False
    next_review_at: datetime | None = None
    interval_days: int | None = None


def _find_player(session: Session, platform: str | None, username: str | None) -> PlayerRow | None:
    if not platform or not username or not username.strip():
        return None
    return session.scalar(
        select(PlayerRow).where(
            PlayerRow.platform == platform,
            PlayerRow.username_normalized == normalize_username(username),
        )
    )


def _drill_out(drill: Drill, progress: DrillProgress | None, now: datetime) -> DrillOut:
    stored = progress or DrillProgress()
    return DrillOut(
        id=drill.id,
        kind=drill.kind,
        title=drill.title,
        category=drill.category,
        fen=drill.fen,
        player_color="white" if drill.player_color == chess.WHITE else "black",
        goal=drill.goal,
        finish=drill.finish,
        move_limit=drill.move_limit,
        summary=drill.summary,
        hint=drill.hint,
        game_id=drill.game_id,
        opponent=drill.opponent,
        played_at=drill.played_at,
        played_san=drill.played_san,
        move_number=drill.move_number,
        attempts=stored.attempts,
        passes=stored.passes,
        last_passed=stored.last_passed,
        due_at=stored.due_at,
        due=stored.due_at is not None and stored.due_at <= now,
    )


@router.get("", response_model=DrillsResponse)
def list_drills(
    user_id: Viewer, platform: str | None = None, username: str | None = None
) -> DrillsResponse:
    """Essentials for everyone; a known player also gets own-game drills and saved progress."""
    with session_scope() as session:
        _require_viewer(session, platform, username, user_id)
        player = _find_player(session, platform, username)
        games = own_game_drills(session, player) if player else []
        progress = drill_progress(session, player) if player else {}
        now = datetime.now(UTC)
        return DrillsResponse(
            drills=[_drill_out(drill, progress.get(drill.fen), now) for drill in [*games, *load_essentials()]]
        )


def _require_viewer(
    session: Session, platform: str | None, username: str | None, user_id: str | None
) -> None:
    if platform and (username or "").strip():
        require_access(session, platform, username, user_id)


def _resolve(drill_id: str, platform: str | None, username: str | None) -> Drill:
    drill = None
    if drill_id.startswith(GAME_DRILL_PREFIX):
        with session_scope() as session:
            player = _find_player(session, platform, username)
            drill = get_game_drill(session, player, drill_id) if player else None
    else:
        drill = get_essential(drill_id)
    if drill is None:
        raise HTTPException(404, "Endgame drill not found.")
    return drill


def _engine_turn(drill: Drill, request: TurnRequest) -> Turn:
    path = engine_binary()
    if not path:
        raise HTTPException(503, "Stockfish is not installed on the server.")
    analyzer = EngineAnalyzer(depth=ENGINE_DEPTH, engine_path=path, max_nodes=ENGINE_MAX_NODES)
    try:
        return play_turn(drill, request.moves_uci, request.strikes, analyzer)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    finally:
        analyzer.close()


def _record(drill: Drill, turn: Turn, request: TurnRequest) -> TurnOut:
    out = TurnOut(
        status=turn.status,
        result=turn.result,
        reason=turn.reason,
        fen=turn.fen,
        reply_san=turn.reply_san,
        reply_uci=turn.reply_uci,
        strikes=turn.strikes,
    )
    username = (request.username or "").strip()
    if turn.status == "playing" or not request.platform or not username:
        return out
    with session_scope() as session:
        player = get_or_create_player(session, request.platform, username)
        schedule = record_result(session, player, drill, turn, request.hints_used, request.elapsed_ms)
        out.recorded = True
        out.next_review_at = schedule.due_at
        out.interval_days = schedule.interval_days
    log_event("endgame_drill_finished", {"drill_id": drill.id, "result": turn.result})
    return out


@router.post("/turn", response_model=TurnOut)
async def take_turn(request: TurnRequest, user_id: Viewer) -> TurnOut:
    """Judge the player's latest move, reply with Stockfish, and record a finished drill."""
    with session_scope() as session:
        _require_viewer(session, request.platform, request.username, user_id)
    drill = await asyncio.to_thread(_resolve, request.drill_id, request.platform, request.username)
    if request.resign:
        turn = Turn("failed", "You stopped the drill.", "resigned", drill.fen)
    else:
        turn = await asyncio.to_thread(_engine_turn, drill, request)
    return await asyncio.to_thread(_record, drill, turn, request)
