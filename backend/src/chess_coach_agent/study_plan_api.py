"""HTTP endpoints for the weekly study plan (see study_plan.py).

GET only reads: it never creates a player or a plan. POST builds the week's plan, and returns the
existing one while the week is running, so a double click cannot make two.
"""

from __future__ import annotations

import asyncio
import os
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .accounts import Viewer, require_access
from .coach_limits import QuotaCharge
from .db import session_scope
from .db_models import GameRow, StudyPlanRow
from .monitoring import log_event
from .openings_api import _find_player
from .study_plan import (
    GAME_RETRY,
    StudyPlanResponse,
    create_plan,
    local_date,
    record_activity,
    study_plan_response,
    write_rationale,
)

router = APIRouter(prefix="/api/study-plan", tags=["study-plan"])


class CreateStudyPlan(BaseModel):
    today: str | None = Field(default=None, description="The player's local date, YYYY-MM-DD")


class GameRetry(BaseModel):
    game_id: str
    ply: int = Field(ge=1)


@router.get("/{platform}/{username}", response_model=StudyPlanResponse)
def get_study_plan(
    platform: str, username: str, user_id: Viewer, today: str | None = Query(default=None)
) -> StudyPlanResponse:
    with session_scope() as session:
        require_access(session, platform, username, user_id)
        player = _find_player(session, platform, username)
        return study_plan_response(session, platform, username, player, local_date(today))


def _build(platform: str, username: str, today: date) -> tuple[str, bool, dict[str, Any]] | None:
    with session_scope() as session:
        player = _find_player(session, platform, username)
        if player is None:
            raise HTTPException(404, "Player not found. Sync some games first.")
        plan = create_plan(session, player, today)
        if plan is None:
            return None
        return plan.id, plan.rationale is None, dict(plan.facts)


async def _limited_rationale(
    facts: dict[str, Any], request: Request, user_id: str | None
) -> tuple[str | None, bool]:
    """The note, if the viewer has quota for one, and whether the limit stopped it.

    The plan is already stored: a slow or failed LLM call, or the limit, only loses the note.
    A note the model wrote that failed verification stays counted. Those plans are asked again on
    every POST, so a refund there would leave them unlimited.
    """
    charge = QuotaCharge(request, user_id, "study_plan")
    if not await asyncio.to_thread(charge.take):
        return None, True
    answered = False
    try:
        rationale, answered = await write_rationale(facts)
    finally:
        if not answered:
            await asyncio.to_thread(charge.refund)
    return rationale, False


@router.post("/{platform}/{username}", response_model=StudyPlanResponse)
async def post_study_plan(
    platform: str, username: str, body: CreateStudyPlan, request: Request, user_id: Viewer
) -> StudyPlanResponse:
    with session_scope() as session:
        require_access(session, platform, username, user_id)
    today = local_date(body.today)
    try:
        built = await asyncio.to_thread(_build, platform, username, today)
    except IntegrityError:  # a parallel request stored this week's plan first
        built = None
    if built is not None:
        plan_id, needs_rationale, facts = built
        rationale = None
        limited = False
        if needs_rationale and os.getenv("OPENROUTER_API_KEY"):
            rationale, limited = await _limited_rationale(facts, request, user_id)
        if rationale:
            with session_scope() as session:
                row = session.get(StudyPlanRow, plan_id)
                if row is not None:
                    row.rationale = rationale
        log_event(
            "study_plan_ready",
            {
                "plan_id": plan_id,
                "tasks": facts.get("tasks"),
                "rationale": bool(rationale),
                "llm_limited": limited,
            },
        )
    with session_scope() as session:
        player = _find_player(session, platform, username)
        return study_plan_response(session, platform, username, player, today)


@router.post("/{platform}/{username}/game-retry")
def post_game_retry(
    platform: str, username: str, body: GameRetry, user_id: Viewer
) -> dict[str, str]:
    """Called by the review page when the player finishes retrying a move on the board."""
    with session_scope() as session:
        require_access(session, platform, username, user_id)
        player = _find_player(session, platform, username)
        game_exists = player is not None and session.scalar(
            select(GameRow.id).where(
                GameRow.player_id == player.id, GameRow.external_game_id == body.game_id
            )
        )
        if not game_exists:
            raise HTTPException(404, "Game not found")
        record_activity(session, player.id, GAME_RETRY, body.game_id, str(body.ply))
    return {"status": "recorded"}
