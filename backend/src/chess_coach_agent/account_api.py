"""Account endpoints for signed-in users: settings and linking a Chess.com player."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy.orm import Session

from .accounts import Viewer, link_player
from .auth import chesscom_code
from .db import session_scope
from .db_models import UserRow
from .importers import CHESSCOM_API_BASE, chesscom_user_agent

router = APIRouter(prefix="/api/account", tags=["account"])

ChessComName = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9_-]{2,50}$")
]


class UserSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speak_answers: bool = False


class ChessComLink(BaseModel):
    username: ChessComName


def _user(session: Session, user_id: str | None) -> UserRow:
    user = session.get(UserRow, user_id) if user_id else None
    if user is None:
        raise HTTPException(401, "Sign in to use this.")
    return user


@router.get("/settings", response_model=UserSettings)
def get_settings(user_id: Viewer) -> UserSettings:
    with session_scope() as session:
        return UserSettings.model_validate(_user(session, user_id).settings or {})


@router.put("/settings", response_model=UserSettings)
def put_settings(body: UserSettings, user_id: Viewer) -> UserSettings:
    with session_scope() as session:
        _user(session, user_id).settings = body.model_dump()
    return body


@router.post("/chesscom/code")
def chesscom_link_code(body: ChessComLink, user_id: Viewer) -> dict[str, str]:
    with session_scope() as session:
        user = _user(session, user_id)
        return {"username": body.username, "code": chesscom_code(user.id, body.username)}


async def _chesscom_profile(username: str) -> dict:
    headers = {"User-Agent": chesscom_user_agent()}
    url = f"{CHESSCOM_API_BASE}/{quote(username.lower(), safe='')}"
    try:
        async with httpx.AsyncClient(timeout=15, headers=headers, follow_redirects=True) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Could not reach Chess.com. Try again shortly.") from exc
    if response.status_code == 404:
        raise HTTPException(404, "Chess.com could not find that username.")
    if response.status_code != 200:
        raise HTTPException(502, "Chess.com did not answer. Try again shortly.")
    return response.json()


@router.post("/chesscom/verify")
async def chesscom_verify(body: ChessComLink, user_id: Viewer) -> dict[str, str]:
    with session_scope() as session:
        signed_in = _user(session, user_id).id
    profile = await _chesscom_profile(body.username)
    code = chesscom_code(signed_in, body.username)
    if code not in f"{profile.get('location') or ''} {profile.get('name') or ''}":
        raise HTTPException(
            422,
            "The code is not on that Chess.com profile yet. "
            "Add it to your Location field, save, and try again.",
        )
    with session_scope() as session:
        link = link_player(session, signed_in, "chess.com", body.username, "chesscom_profile")
        if link.user_id != signed_in:
            raise HTTPException(409, "That Chess.com player is linked to another account.")
    return {"platform": "chess.com", "username": body.username}
