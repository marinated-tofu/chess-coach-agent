"""Daily limits on the practice agent, study plan rationale and board reading."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_study_plan import _seed

from chess_coach_agent import coach_limits, practice_agent, quiz_copy, study_plan_api, vision_api
from chess_coach_agent.api import app
from chess_coach_agent.auth import SESSION_COOKIE, sign
from chess_coach_agent.coach_limits import QuotaScope, coach_quota, take_quota
from chess_coach_agent.db import session_scope
from chess_coach_agent.db_models import UserRow
from chess_coach_agent.vision import VisionResult, VisionUnavailable

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _user() -> str:
    with session_scope() as session:
        user = UserRow(display_name="Limits")
        session.add(user)
        session.flush()
        return user.id


def _client(user_id: str) -> TestClient:
    client = TestClient(app, raise_server_exceptions=False)
    client.cookies.set(SESSION_COOKIE, sign({"uid": user_id}, "session"))
    return client


def _used(user_id: str, feature: str) -> int:
    with session_scope() as session:
        return coach_quota(session, QuotaScope(f"user:{user_id}", "free", feature)).used


def test_each_feature_counts_apart_with_its_own_limit(monkeypatch):
    monkeypatch.setenv("VISION_DAILY_LIMIT_FREE", "1")
    monkeypatch.setenv("COACH_DAILY_LIMIT_FREE", "1")
    subject = f"user:{uuid4().hex}"
    with session_scope() as session:
        assert take_quota(session, QuotaScope(subject, "free", "vision"))
        assert not take_quota(session, QuotaScope(subject, "free", "vision"))
        assert take_quota(session, QuotaScope(subject, "free"))


def test_limit_defaults_are_per_feature(monkeypatch):
    monkeypatch.delenv("VISION_DAILY_LIMIT_ANONYMOUS", raising=False)
    assert coach_limits.daily_limit("anonymous", "vision") == 3
    assert coach_limits.daily_limit("paid") == 200


# ---------------------------------------------------------------- vision


def _read_ok(*_args, **_kwargs):
    async def run():
        return VisionResult(
            fen="8/8/8/8/8/8/8/8 w - - 0 1",
            side_to_move_guess="white",
            confidence=0.9,
            warnings=[],
            board_ascii="",
            valid=True,
            orientation="white_at_bottom",
            attempts=1,
        )

    return run()


def _upload(client: TestClient):
    return client.post("/api/vision/fen", files={"image": ("board.png", PNG, "image/png")})


def test_vision_returns_429_with_retry_after_at_the_limit(monkeypatch):
    monkeypatch.setenv("VISION_DAILY_LIMIT_FREE", "1")
    monkeypatch.setattr(vision_api, "read_board_image", _read_ok)
    client = _client(_user())
    assert _upload(client).status_code == 200

    blocked = _upload(client)
    assert blocked.status_code == 429
    assert "1 board image read for today" in blocked.json()["detail"]
    assert int(blocked.headers["retry-after"]) > 0


def test_invalid_upload_does_not_use_the_limit(monkeypatch):
    user_id = _user()
    response = _client(user_id).post(
        "/api/vision/fen", files={"image": ("notes.txt", b"hello", "text/plain")}
    )
    assert response.status_code == 415
    assert _used(user_id, "vision") == 0


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (VisionUnavailable("no key"), 503),
        (TimeoutError(), 504),
        (RuntimeError("provider down"), 502),
    ],
)
def test_vision_failures_are_refunded(monkeypatch, error, status):
    async def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(vision_api, "read_board_image", fail)
    user_id = _user()
    assert _upload(_client(user_id)).status_code == status
    assert _used(user_id, "vision") == 0


def test_unreadable_image_stays_counted_or_non_boards_would_be_free(monkeypatch):
    async def unreadable(*_args, **_kwargs):
        raise ValueError("The model did not return a readable 8x8 board.")

    monkeypatch.setattr(vision_api, "read_board_image", unreadable)
    user_id = _user()
    assert _upload(_client(user_id)).status_code == 422
    assert _used(user_id, "vision") == 1


# ---------------------------------------------------------------- practice


SESSION = {"platform": "chess.com", "username": "", "position_count": 3, "mode": "puzzles"}


def _practice(client: TestClient, **overrides):
    username = overrides.pop("username", f"limits-{uuid4().hex[:8]}")
    return client.post("/api/training/sessions", json={**SESSION, "username": username, **overrides})


@pytest.fixture
def llm_calls(monkeypatch):
    """Every way a practice session reaches the model, counted, with a working key."""
    calls: list[str] = []
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    def complete(system, prompt, temperature=0.0):
        calls.append(prompt)
        return '{"prompt": "What would you play?", "hint": null}', True

    monkeypatch.setattr(quiz_copy, "complete_with_openrouter_sync", complete)
    monkeypatch.setattr(practice_agent, "_openrouter_model", lambda: None)
    return calls


def test_practice_at_the_limit_builds_a_session_without_the_model(monkeypatch, llm_calls):
    monkeypatch.setenv("PRACTICE_DAILY_LIMIT_FREE", "1")
    user_id = _user()
    client = _client(user_id)

    first = _practice(client)
    assert first.status_code == 200, first.text
    assert llm_calls
    assert _used(user_id, "practice") == 1

    llm_calls.clear()
    second = _practice(client)
    assert second.status_code == 200, second.text
    assert len(second.json()["positions"]) == len(first.json()["positions"])
    assert llm_calls == []
    assert _used(user_id, "practice") == 1


def test_practice_refunds_when_the_model_never_answered(monkeypatch, llm_calls):
    monkeypatch.setattr(quiz_copy, "complete_with_openrouter_sync", lambda *_a, **_k: ("", False))
    user_id = _user()
    assert _practice(_client(user_id)).status_code == 200
    assert _used(user_id, "practice") == 0


def test_practice_refunds_when_building_the_session_fails(monkeypatch, llm_calls):
    def explode(*_args, **_kwargs):
        raise RuntimeError("no positions")

    monkeypatch.setattr(practice_agent, "build_training_session", explode)
    user_id = _user()
    assert _practice(_client(user_id)).status_code == 500
    assert _used(user_id, "practice") == 0


def test_practice_without_a_key_uses_no_quota(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("PRACTICE_DAILY_LIMIT_FREE", "0")
    user_id = _user()
    assert _practice(_client(user_id)).status_code == 200
    assert _used(user_id, "practice") == 0


# ---------------------------------------------------------------- study plan


def _plan(monkeypatch, note: tuple[str | None, bool]) -> tuple[str, TestClient, str, list[int]]:
    """A seeded player and a signed-in client, with the model's answer replaced."""
    calls: list[int] = []

    async def fake_write(_facts):
        calls.append(1)
        return note

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(study_plan_api, "write_rationale", fake_write)
    username = f"plan-limits-{uuid4().hex[:8]}"
    _seed(username)
    user_id = _user()
    return user_id, _client(user_id), f"/api/study-plan/lichess/{username}", calls


def test_plan_at_the_limit_is_built_without_a_note(monkeypatch):
    monkeypatch.setenv("STUDY_PLAN_DAILY_LIMIT_FREE", "0")
    user_id, client, url, calls = _plan(monkeypatch, ("A note.", True))
    response = client.post(url, json={})
    assert response.status_code == 200, response.text
    plan = response.json()["plan"]
    assert plan["rationale"] is None
    assert plan["summary"]
    assert calls == []


def test_plan_note_is_counted(monkeypatch):
    user_id, client, url, _calls = _plan(monkeypatch, ("A note.", True))
    assert client.post(url, json={}).json()["plan"]["rationale"] == "A note."
    assert _used(user_id, "study_plan") == 1


def test_failed_plan_note_is_refunded(monkeypatch):
    user_id, client, url, _calls = _plan(monkeypatch, (None, False))
    assert client.post(url, json={}).status_code == 200
    assert _used(user_id, "study_plan") == 0


def test_rejected_plan_notes_stay_counted_so_retries_hit_the_limit(monkeypatch):
    """A plan without a note asks the model again on each POST, however it lost the note."""
    monkeypatch.setenv("STUDY_PLAN_DAILY_LIMIT_FREE", "2")
    user_id, client, url, calls = _plan(monkeypatch, (None, True))
    for _ in range(4):
        assert client.post(url, json={}).status_code == 200
    assert len(calls) == 2
    assert _used(user_id, "study_plan") == 2
