"""Bot personas and human-like bot moves for the Play page (model documented in bots.py)."""

from __future__ import annotations

import asyncio
import random
import threading

import chess
import chess.engine
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .bots import (
    BOTS,
    BOTS_BY_ID,
    BotContext,
    blunder_chance,
    choose_move,
    player_rating,
    sparring_book,
    thinking_ms,
    tsv_book,
)
from .engine_api import engine_binary, game_result, parse_fen

router = APIRouter(prefix="/api/bots")

# Parse the openings TSV in the background so the first bot move doesn't pay for it (~2 s).
threading.Thread(target=tsv_book, name="bot-book-warmup", daemon=True).start()


class BotOut(BaseModel):
    id: str
    name: str
    rating: int
    style: str
    blurb: str
    initial: str
    color: str
    blunder_rate: float  # base chance per move, before the complexity factor


class BotsResponse(BaseModel):
    bots: list[BotOut]


class BotMoveRequest(BaseModel):
    fen: str
    bot_id: str
    moves_uci: list[str] | None = None
    platform: str | None = None
    username: str | None = None
    seed: int | None = None


class BotMoveOut(BaseModel):
    move_san: str
    move_uci: str
    fen_after: str
    thinking_ms: int
    source: str  # book | sparring | engine | blunder | only
    rating: int
    comment: str | None = None


@router.get("", response_model=BotsResponse)
def list_bots() -> BotsResponse:
    return BotsResponse(
        bots=[
            BotOut(
                id=bot.id,
                name=bot.name,
                rating=bot.rating,
                style=bot.style,
                blurb=bot.blurb,
                initial=bot.initial,
                color=bot.color,
                blunder_rate=round(blunder_chance(bot.rating), 3),
            )
            for bot in BOTS
        ]
    )


def _ply(board: chess.Board, moves_uci: list[str] | None) -> int:
    if moves_uci is not None:
        return len(moves_uci)
    return (board.fullmove_number - 1) * 2 + (0 if board.turn == chess.WHITE else 1)


def _play(request: BotMoveRequest, board: chess.Board) -> BotMoveOut:
    bot = BOTS_BY_ID[request.bot_id]
    rng = random.Random(request.seed)
    rating = bot.rating
    sparring: dict = {}
    note: str | None = None
    if bot.style == "sparring" and request.username:
        rating = player_rating(request.platform, request.username) or bot.rating
        sparring = sparring_book(request.platform, request.username)
        if not sparring:
            note = "No stored games for this player yet, so I'm playing popular book lines."
    context = BotContext(bot=bot, rating=rating, ply=_ply(board, request.moves_uci), sparring=sparring)

    engine: chess.engine.SimpleEngine | None = None
    try:
        path = engine_binary()
        if path:
            engine = chess.engine.SimpleEngine.popen_uci(path)
        try:
            decision = choose_move(engine, board, context, rng)
        except ValueError as error:
            raise HTTPException(503, "Stockfish is not installed on the server.") from error
    finally:
        if engine is not None:
            engine.quit()

    san = board.san(decision.move)
    if decision.source == "sparring":
        games = decision.book_games
        note = f"Your opponents played {san} here in {games} game{'s' if games != 1 else ''}."
    board.push(decision.move)
    return BotMoveOut(
        move_san=san,
        move_uci=decision.move.uci(),
        fen_after=board.fen(),
        thinking_ms=thinking_ms(decision, rating, rng),
        source=decision.source,
        rating=rating,
        comment=note,
    )


@router.post("/move", response_model=BotMoveOut)
async def bot_move(request: BotMoveRequest) -> BotMoveOut:
    if request.bot_id not in BOTS_BY_ID:
        raise HTTPException(404, f"Unknown bot '{request.bot_id}'.")
    board = parse_fen(request.fen)
    result = game_result(board)
    if result:
        raise HTTPException(422, f"The game is already over ({result.replace('_', ' ')}).")
    return await asyncio.to_thread(_play, request, board)
