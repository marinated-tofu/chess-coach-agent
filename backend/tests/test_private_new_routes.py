"""Routes added alongside accounts must refuse another user's claimed player."""

from __future__ import annotations

from sqlalchemy import select

import pytest
from fastapi.testclient import TestClient

from chess_coach_agent.api import app
from chess_coach_agent.db import init_db, session_scope
from chess_coach_agent.db_models import UserPlayerRow, UserRow
from chess_coach_agent.repositories import get_or_create_player


@pytest.fixture
def claimed():
    init_db()
    with session_scope() as session:
        player = get_or_create_player(session, "lichess", "claimed_private_player")
        if session.scalar(select(UserPlayerRow).where(UserPlayerRow.player_id == player.id)) is None:
            user = UserRow(display_name="owner")
            session.add(user)
            session.flush()
            session.add(UserPlayerRow(user_id=user.id, player_id=player.id, verified_by="lichess_oauth"))
    return "lichess", "claimed_private_player"


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/api/study-plan/lichess/claimed_private_player", None),
        ("post", "/api/study-plan/lichess/claimed_private_player", {}),
        ("post", "/api/study-plan/lichess/claimed_private_player/game-retry", {"game_id": "x", "ply": 1}),
        ("get", "/api/endgames?platform=lichess&username=claimed_private_player", None),
        ("get", "/api/puzzles?platform=lichess&username=claimed_private_player", None),
    ],
)
def test_anonymous_viewer_is_refused(claimed, method, path, body):
    client = TestClient(app)
    response = client.request(method, path, json=body)
    assert response.status_code == 401
