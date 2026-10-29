"""Stockfish endpoints for the analysis board: multi-line analysis and a level-limited bot."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

import chess
import chess.engine
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .engine import stockfish_path

router = APIRouter(prefix="/api/engine")

HOMEBREW_STOCKFISH = "/opt/homebrew/bin/stockfish"
MAX_DEPTH = 18
MAX_MOVETIME_MS = 1500
PV_LENGTH = 8


def engine_binary() -> str | None:
    """Same lookup as EngineAnalyzer (STOCKFISH_PATH, then PATH), plus the Homebrew default."""
    found = stockfish_path()
    if found:
        return found
    return HOMEBREW_STOCKFISH if os.path.exists(HOMEBREW_STOCKFISH) else None


class AnalyzeEngineRequest(BaseModel):
    fen: str
    multipv: int = Field(default=3, ge=1, le=3)
    depth: int | None = Field(default=None, ge=1)
    movetime_ms: int | None = Field(default=None, ge=10)


class EngineLineOut(BaseModel):
    rank: int
    move_san: str
    move_uci: str
    eval_cp: int | None = None  # White's point of view
    mate: int | None = None  # White's point of view: > 0 White mates in n, < 0 Black mates
    pv_san: list[str]


class AnalyzeEngineResponse(BaseModel):
    fen: str
    side_to_move: str
    lines: list[EngineLineOut]
    depth: int | None = None
    result: str | None = None


class BotMoveRequest(BaseModel):
    fen: str
    level: int = Field(default=3, ge=1, le=8)


class BotMoveResponse(BaseModel):
    move_san: str
    move_uci: str
    fen_after: str
    level: int


@dataclass(frozen=True)
class BotLevel:
    elo: int  # nominal strength shown to players
    movetime_ms: int
    skill: int | None = None  # Stockfish "Skill Level" for levels below the UCI_Elo floor
    depth: int | None = None


# Stockfish's UCI_Elo floor is 1320, so the three lowest levels use Skill Level plus a shallow
# depth instead. Higher levels let UCI_LimitStrength calibrate the strength.
BOT_LEVELS: dict[int, BotLevel] = {
    1: BotLevel(elo=800, movetime_ms=50, skill=0, depth=1),
    2: BotLevel(elo=1000, movetime_ms=80, skill=2, depth=2),
    3: BotLevel(elo=1200, movetime_ms=120, skill=4, depth=4),
    4: BotLevel(elo=1400, movetime_ms=200),
    5: BotLevel(elo=1600, movetime_ms=250),
    6: BotLevel(elo=1800, movetime_ms=300),
    7: BotLevel(elo=2100, movetime_ms=400),
    8: BotLevel(elo=2400, movetime_ms=500),
}


def parse_fen(fen: str) -> chess.Board:
    try:
        board = chess.Board(fen.strip())
    except ValueError as error:
        raise HTTPException(422, f"Invalid FEN: {error}") from error
    if not board.is_valid():
        raise HTTPException(422, "Invalid FEN: the position is not legal.")
    return board


def game_result(board: chess.Board) -> str | None:
    outcome = board.outcome(claim_draw=True)
    return outcome.termination.name.lower() if outcome else None


def _open_engine() -> chess.engine.SimpleEngine:
    path = engine_binary()
    if not path:
        raise HTTPException(503, "Stockfish is not installed on the server.")
    return chess.engine.SimpleEngine.popen_uci(path)


def _pv_san(board: chess.Board, pv: list[chess.Move]) -> list[str]:
    walk = board.copy(stack=False)
    sans: list[str] = []
    for move in pv[:PV_LENGTH]:
        if move not in walk.legal_moves:
            break
        sans.append(walk.san(move))
        walk.push(move)
    return sans


def _analyse(board: chess.Board, multipv: int, limit: chess.engine.Limit) -> AnalyzeEngineResponse:
    engine = _open_engine()
    try:
        infos = engine.analyse(board, limit, multipv=multipv)
    finally:
        engine.quit()
    lines: list[EngineLineOut] = []
    depth = 0
    for info in infos:
        pv = info.get("pv") or []
        if not pv or "score" not in info:
            continue
        white = info["score"].white()
        depth = max(depth, info.get("depth") or 0)
        lines.append(
            EngineLineOut(
                rank=len(lines) + 1,
                move_san=board.san(pv[0]),
                move_uci=pv[0].uci(),
                eval_cp=white.score(),
                mate=white.mate(),
                pv_san=_pv_san(board, pv),
            )
        )
    return AnalyzeEngineResponse(
        fen=board.fen(),
        side_to_move="white" if board.turn == chess.WHITE else "black",
        lines=lines,
        depth=depth or None,
    )


def _bot_move(board: chess.Board, level: int) -> chess.Move:
    settings = BOT_LEVELS[level]
    engine = _open_engine()
    try:
        if settings.skill is not None:
            engine.configure({"UCI_LimitStrength": False, "Skill Level": settings.skill})
        else:
            engine.configure({"UCI_LimitStrength": True, "UCI_Elo": settings.elo})
        limit = chess.engine.Limit(time=settings.movetime_ms / 1000, depth=settings.depth)
        result = engine.play(board, limit)
    finally:
        engine.quit()
    if result.move is None:
        raise HTTPException(500, "The engine did not return a move.")
    return result.move


@router.post("/analyze", response_model=AnalyzeEngineResponse)
async def analyze_position(request: AnalyzeEngineRequest) -> AnalyzeEngineResponse:
    board = parse_fen(request.fen)
    result = game_result(board)
    if result:
        return AnalyzeEngineResponse(
            fen=board.fen(),
            side_to_move="white" if board.turn == chess.WHITE else "black",
            lines=[],
            result=result,
        )
    if request.movetime_ms is not None:
        limit = chess.engine.Limit(time=min(request.movetime_ms, MAX_MOVETIME_MS) / 1000)
    else:
        limit = chess.engine.Limit(depth=min(request.depth or 14, MAX_DEPTH))
    return await asyncio.to_thread(_analyse, board, request.multipv, limit)


@router.post("/move", response_model=BotMoveResponse)
async def bot_move(request: BotMoveRequest) -> BotMoveResponse:
    board = parse_fen(request.fen)
    if game_result(board):
        raise HTTPException(422, "The game is already over in this position.")
    move = await asyncio.to_thread(_bot_move, board, request.level)
    san = board.san(move)
    board.push(move)
    return BotMoveResponse(move_san=san, move_uci=move.uci(), fen_after=board.fen(), level=request.level)
