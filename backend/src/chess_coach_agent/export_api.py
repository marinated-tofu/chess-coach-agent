from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from .db import session_scope
from .pgn_export import build_annotated_pgn, pgn_filename
from .repositories import load_analyses

router = APIRouter(prefix="/api")


@router.get("/games/{platform}/{username}/{game_id}/pgn", response_class=PlainTextResponse)
def export_game_pgn(
    platform: str,
    username: str,
    game_id: str,
    evals: bool = True,
    clocks: bool = True,
    variations: bool = True,
) -> PlainTextResponse:
    with session_scope() as session:
        analyses = load_analyses(session, platform, username, game_id).analyses
    if not analyses:
        raise HTTPException(404, "Game not found")
    analysis = analyses[0]
    pgn = build_annotated_pgn(
        analysis,
        include_evals=evals,
        include_clocks=clocks,
        include_variations=variations,
    )
    return PlainTextResponse(
        pgn,
        media_type="application/x-chess-pgn",
        headers={"Content-Disposition": f'attachment; filename="{pgn_filename(analysis)}"'},
    )
