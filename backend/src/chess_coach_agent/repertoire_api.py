"""HTTP endpoints for opening repertoires (see repertoire.py)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import session_scope
from .db_models import PlayerRow, RepertoireRow
from .repertoire import (
    RepertoireError,
    add_move,
    answer,
    build_tree,
    count_due,
    drill_items,
    remove_move,
    seed_from_games,
)
from .repositories import normalize_username

router = APIRouter(prefix="/api/repertoire", tags=["repertoire"])

Color = Literal["white", "black"]


class CreateRepertoire(BaseModel):
    platform: str
    username: str
    color: Color
    name: str = ""


class AddMove(BaseModel):
    parent_fen: str = Field(description="FEN (or EPD) of the position the move is played from")
    move: str = Field(description="SAN or UCI")
    comment: str = ""


class DrillAnswer(BaseModel):
    move_id: str
    move: str


def _player(session: Session, platform: str, username: str) -> PlayerRow:
    player = session.scalar(
        select(PlayerRow).where(
            PlayerRow.platform == platform,
            PlayerRow.username_normalized == normalize_username(username),
        )
    )
    if player is None:
        raise HTTPException(404, "Player not found. Sync some games first.")
    return player


def _rep(session: Session, rep_id: str) -> RepertoireRow:
    rep = session.get(RepertoireRow, rep_id)
    if rep is None:
        raise HTTPException(404, "Repertoire not found")
    return rep


def _summary(session: Session, rep: RepertoireRow) -> dict[str, Any]:
    return {
        "id": rep.id,
        "color": rep.color,
        "name": rep.name,
        "created_at": rep.created_at.isoformat(),
        "due_count": count_due(session, rep),
    }


def _full(session: Session, rep: RepertoireRow) -> dict[str, Any]:
    return {**_summary(session, rep), "tree": build_tree(session, rep)}


@router.get("")
def list_repertoires(platform: str, username: str) -> list[dict[str, Any]]:
    with session_scope() as session:
        player = _player(session, platform, username)
        reps = session.scalars(
            select(RepertoireRow)
            .where(RepertoireRow.player_id == player.id)
            .order_by(RepertoireRow.created_at)
        )
        return [_summary(session, rep) for rep in reps]


@router.post("")
def create_repertoire(body: CreateRepertoire) -> dict[str, Any]:
    with session_scope() as session:
        player = _player(session, body.platform, body.username)
        name = body.name.strip() or f"{body.color.capitalize()} repertoire"
        rep = RepertoireRow(player_id=player.id, color=body.color, name=name[:100])
        session.add(rep)
        session.flush()
        return _full(session, rep)


@router.get("/{rep_id}")
def get_repertoire(rep_id: str) -> dict[str, Any]:
    with session_scope() as session:
        return _full(session, _rep(session, rep_id))


@router.delete("/{rep_id}")
def delete_repertoire(rep_id: str) -> dict[str, str]:
    with session_scope() as session:
        session.delete(_rep(session, rep_id))
    return {"status": "deleted"}


@router.post("/{rep_id}/moves")
def post_move(rep_id: str, body: AddMove) -> dict[str, Any]:
    with session_scope() as session:
        rep = _rep(session, rep_id)
        try:
            row, created = add_move(session, rep, body.parent_fen, body.move, comment=body.comment)
        except RepertoireError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"move_id": row.id, "san": row.san, "created": created, **_full(session, rep)}


@router.delete("/{rep_id}/moves/{move_id}")
def delete_move(rep_id: str, move_id: str) -> dict[str, Any]:
    with session_scope() as session:
        rep = _rep(session, rep_id)
        try:
            removed = remove_move(session, rep, move_id)
        except RepertoireError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"removed": removed, **_full(session, rep)}


@router.post("/{rep_id}/seed")
def seed(rep_id: str) -> dict[str, Any]:
    with session_scope() as session:
        rep = _rep(session, rep_id)
        report = seed_from_games(session, rep)
        return {
            "games_used": report.games_used,
            "added": report.added,
            "flagged": report.flagged,
            **_full(session, rep),
        }


@router.get("/{rep_id}/drill")
def drill(
    rep_id: str,
    limit: int = Query(default=10, ge=1, le=50),
    include_all: bool = Query(default=False, description="Practice moves that are not due yet"),
) -> dict[str, Any]:
    with session_scope() as session:
        rep = _rep(session, rep_id)
        return {
            "due_count": count_due(session, rep),
            "items": drill_items(session, rep, limit=limit, include_all=include_all),
        }


@router.post("/{rep_id}/drill/answer")
def drill_answer(rep_id: str, body: DrillAnswer) -> dict[str, Any]:
    with session_scope() as session:
        rep = _rep(session, rep_id)
        try:
            result = answer(session, rep, body.move_id, body.move)
        except RepertoireError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {**result, "due_count": count_due(session, rep)}
