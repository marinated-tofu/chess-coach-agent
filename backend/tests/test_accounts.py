import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import select

from chess_coach_agent import account_api, adaptive_api, coach_limits, coach_tools, monitoring
from chess_coach_agent.accounts import link_player, sign_in_user
from chess_coach_agent.api import app
from chess_coach_agent.auth import SESSION_COOKIE, chesscom_code, sign
from chess_coach_agent.coach_limits import QuotaScope, coach_quota, take_quota
from chess_coach_agent.db import session_scope
from chess_coach_agent.db_models import (
    AuthIdentityRow,
    GameRow,
    PlayerMemoryRow,
    QuizAttemptRow,
    RepertoireRow,
    ReviewScheduleRow,
    TrainingPlanRow,
    TrainingPositionRow,
    UserPlayerRow,
    UserRow,
)
from chess_coach_agent.llm import CoachDependencies
from chess_coach_agent.repositories import get_or_create_player

BACKEND = Path(__file__).resolve().parents[1]
REAL_ASYNC_CLIENT = httpx.AsyncClient


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("TRUSTED_PROXY_HOPS", raising=False)
    for name in coach_limits.LIMIT_ENV.values():
        monkeypatch.delenv(name, raising=False)


def _user(plan: str = "free") -> str:
    with session_scope() as session:
        user = sign_in_user(session, "lichess", uuid4().hex, "Tester")
        user.plan = plan
        return user.id


def _client(user_id: str | None = None) -> TestClient:
    client = TestClient(app)
    if user_id:
        client.cookies.set(SESSION_COOKIE, sign({"uid": user_id}, "session"))
    return client


def _owned_player(user_id: str, platform: str = "lichess") -> tuple[str, str]:
    username = f"p-{uuid4().hex[:10]}"
    with session_scope() as session:
        link_player(session, user_id, platform, username, "lichess_oauth")
        return session.get_one(UserPlayerRow, _player_id(session, platform, username)).player_id, username


def _player_id(session, platform: str, username: str) -> str:
    return get_or_create_player(session, platform, username).id


def _plan(player_id: str) -> tuple[str, str]:
    with session_scope() as session:
        plan = TrainingPlanRow(player_id=player_id, focus_themes=["tactics"])
        session.add(plan)
        session.flush()
        position = TrainingPositionRow(
            plan_id=plan.id,
            position_order=1,
            fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            correct_move="e4",
            choices=["e4", "d4"],
            theme="tactics",
            difficulty="intermediate",
        )
        session.add(position)
        session.flush()
        return plan.id, position.id


def _repertoire(player_id: str) -> str:
    with session_scope() as session:
        rep = RepertoireRow(player_id=player_id, color="white", name="Mine")
        session.add(rep)
        session.flush()
        return rep.id


# ---------------------------------------------------------------- sign-in


def test_lichess_identity_creates_one_free_user_and_owns_the_player():
    subject = uuid4().hex
    with session_scope() as session:
        user = sign_in_user(session, "lichess", subject, "Magnus")
        again = sign_in_user(session, "lichess", subject, "Magnus")
        assert again.id == user.id
        assert user.plan == "free"
        link_player(session, user.id, "lichess", subject, "lichess_oauth")
        user_id = user.id

    me = _client(user_id).get("/api/auth/me").json()
    assert me["signed_in"] is True
    assert me["lichess_username"] == subject
    assert me["plan"] == "free"
    assert me["players"] == [{"platform": "lichess", "username": subject}]
    assert me["coach_quota"]["limit"] == 20


def test_new_identity_attaches_to_the_signed_in_user():
    # The path a second provider such as Google takes; nothing here is Lichess-specific.
    user_id = _user()
    with session_scope() as session:
        attached = sign_in_user(
            session, "google", uuid4().hex, "T", email="t@example.com", current_user_id=user_id
        )
        assert attached.id == user_id
        rows = session.scalars(
            select(AuthIdentityRow).where(AuthIdentityRow.user_id == user_id)
        ).all()
        assert sorted(row.provider for row in rows) == ["google", "lichess"]


def test_old_cookie_and_unknown_user_count_as_signed_out():
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, sign({"lichess_username": "someone"}, "session"))
    assert client.get("/api/auth/me").json()["signed_in"] is False
    assert _client("no-such-user").get("/api/auth/me").json()["signed_in"] is False


def test_plan_rejects_unknown_values():
    with pytest.raises(Exception), session_scope() as session:
        session.add(UserRow(display_name="x", plan="platinum"))


# ---------------------------------------------------------------- personal data


@pytest.mark.parametrize(
    "user,expected",
    [("anonymous", 401), ("other", 403), ("owner", 200)],
)
def test_repertoire_belongs_to_its_owner(user, expected):
    owner = _user()
    player_id, username = _owned_player(owner)
    rep_id = _repertoire(player_id)
    viewer = {"anonymous": None, "other": _user(), "owner": owner}[user]
    client = _client(viewer)

    params = {"platform": "lichess", "username": username}
    start = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    assert client.get("/api/repertoire", params=params).status_code == expected
    assert client.get(f"/api/repertoire/{rep_id}").status_code == expected
    assert client.get(f"/api/repertoire/{rep_id}/drill").status_code == expected
    created = client.post("/api/repertoire", json={**params, "color": "black"})
    assert created.status_code == expected
    added = client.post(
        f"/api/repertoire/{rep_id}/moves", json={"parent_fen": start, "move": "e4"}
    )
    assert added.status_code == expected
    seeded = client.post(f"/api/repertoire/{rep_id}/seed")
    assert seeded.status_code == expected
    answered = client.post(
        f"/api/repertoire/{rep_id}/drill/answer", json={"move_id": "x", "move": "e4"}
    )
    assert answered.status_code == (404 if expected == 200 else expected)
    deleted = client.delete(f"/api/repertoire/{rep_id}/moves/x")
    assert deleted.status_code == (404 if expected == 200 else expected)
    assert client.delete(f"/api/repertoire/{rep_id}").status_code == expected
    with session_scope() as session:
        assert (session.get(RepertoireRow, rep_id) is None) == (expected == 200)


@pytest.mark.parametrize("user,expected", [("anonymous", 401), ("other", 403)])
def test_practice_sessions_are_closed_to_others(user, expected):
    owner = _user()
    player_id, username = _owned_player(owner)
    plan_id, position_id = _plan(player_id)
    client = _client(None if user == "anonymous" else _user())

    assert client.get(f"/api/training/sessions/{plan_id}").status_code == expected
    attempt = client.post(
        f"/api/training/sessions/{plan_id}/attempts",
        json={"position_id": position_id, "move": "e4"},
    )
    assert attempt.status_code == expected
    created = client.post(
        "/api/training/sessions", json={"platform": "lichess", "username": username}
    )
    assert created.status_code == expected
    with session_scope() as session:
        assert session.scalars(
            select(QuizAttemptRow).where(QuizAttemptRow.player_id == player_id)
        ).all() == []
        plans = session.scalars(
            select(TrainingPlanRow).where(TrainingPlanRow.player_id == player_id)
        ).all()
        assert len(plans) == 1


def test_owner_can_answer_their_own_practice_session():
    owner = _user()
    player_id, _ = _owned_player(owner)
    plan_id, position_id = _plan(player_id)
    client = _client(owner)
    assert client.get(f"/api/training/sessions/{plan_id}").status_code == 200
    attempt = client.post(
        f"/api/training/sessions/{plan_id}/attempts",
        json={"position_id": position_id, "move": "e4"},
    )
    assert attempt.status_code == 200


def test_public_stats_stay_viewable_but_practice_figures_do_not():
    owner = _user()
    player_id, username = _owned_player(owner)
    plan_id, position_id = _plan(player_id)
    with session_scope() as session:
        session.add(
            GameRow(
                player_id=player_id,
                external_game_id="g1",
                white=username,
                black="x",
                result="1-0",
                player_result="win",
                player_color="white",
            )
        )
        session.add(
            ReviewScheduleRow(
                player_id=player_id,
                position_id=position_id,
                due_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
        memory = session.get(PlayerMemoryRow, player_id)
        memory.due_positions = 1
        memory.quiz_accuracy = {"tactics": 0.5}
    with session_scope() as session:
        session.add(
            QuizAttemptRow(
                player_id=player_id,
                position_id=position_id,
                submitted_move="e4",
                correct=True,
                legal=True,
            )
        )

    anonymous = _client()
    progress = anonymous.get(f"/api/progress/lichess/{username}").json()
    assert progress["total_games"] == 1
    assert progress["private"] is True
    assert progress["recent_attempts"] == 0
    assert progress["quiz_accuracy"] == {}
    assert progress["player"]["due_positions"] == 0
    assert anonymous.get(f"/api/players/lichess/{username}").json()["quiz_accuracy"] == {}
    today = anonymous.get(f"/api/today/lichess/{username}").json()
    assert today["known"] is True
    assert today["private"] is True
    assert today["due"]["count"] == 0
    queue = anonymous.get(f"/api/library/lichess/{username}/practice-queue").json()
    assert queue["due_count"] == 0
    assert anonymous.get(f"/api/games/lichess/{username}").status_code == 200
    assert anonymous.get(f"/api/library/lichess/{username}").status_code == 200
    assert anonymous.get(f"/api/insights/lichess/{username}").status_code == 200

    mine = _client(owner)
    assert mine.get(f"/api/progress/lichess/{username}").json()["recent_attempts"] == 1
    assert mine.get(f"/api/progress/lichess/{username}").json()["private"] is False
    assert mine.get(f"/api/today/lichess/{username}").json()["due"]["count"] == 1
    queue = mine.get(f"/api/library/lichess/{username}/practice-queue").json()
    assert queue["due_count"] == 1


def test_anonymous_try_out_still_works_for_an_unclaimed_username():
    username = f"demo-{uuid4().hex[:10]}"
    client = _client()
    with session_scope() as session:
        player_id = get_or_create_player(session, "chess.com", username).id
    assert client.get(f"/api/progress/chess.com/{username}").json()["private"] is False
    created = client.post(
        "/api/repertoire", json={"platform": "chess.com", "username": username, "color": "white"}
    )
    assert created.status_code == 200
    plan_id, _ = _plan(player_id)
    assert client.get(f"/api/training/sessions/{plan_id}").status_code == 200
    asked = client.post(
        "/api/coach/ask",
        json={"question": "Hi", "platform": "chess.com", "username": username},
    )
    assert asked.status_code == 200


def test_pasted_games_cannot_be_added_to_someone_elses_player():
    owner = _user()
    _, username = _owned_player(owner)
    pgn = _client().get("/api/sample").json()["pgn"]
    body = {"pgn": pgn, "player": username, "platform": "lichess", "max_games": 1}
    assert _client().post("/api/analyze", json=body).status_code == 401
    assert _client(_user()).post("/api/analyze", json=body).status_code == 403


def test_coach_gets_no_player_identity_without_access(monkeypatch):
    owner = _user()
    player_id, username = _owned_player(owner)
    with session_scope() as session:
        session.get(PlayerMemoryRow, player_id).quiz_accuracy = {"tactics": 0.25}
    seen = {}
    real = adaptive_api.ask_coach

    async def capture(question, analysis, **kwargs):
        seen.update(kwargs)
        return await real(question, analysis)

    monkeypatch.setattr(adaptive_api, "ask_coach", capture)
    body = {"question": "How am I doing?", "platform": "lichess", "username": username}

    assert _client(_user()).post("/api/coach/ask", json=body).status_code == 200
    assert seen["username"] is None and seen["platform"] is None
    assert seen["memory_context"] == ""

    assert _client(owner).post("/api/coach/ask", json=body).status_code == 200
    assert seen["username"] == username
    assert "25%" in seen["memory_context"]


def _ctx(platform: str | None, username: str | None) -> SimpleNamespace:
    return SimpleNamespace(deps=CoachDependencies(platform=platform, username=username))


def test_coach_tools_refuse_positions_and_plans_of_other_players():
    owner = _user()
    player_id, username = _owned_player(owner)
    plan_id, position_id = _plan(player_id)
    other = f"p-{uuid4().hex[:10]}"
    for ctx in (_ctx("lichess", other), _ctx(None, None)):
        assert "error" in coach_tools.evaluate_candidate_move(ctx, position_id, "e4")
        assert "error" in coach_tools.write_quiz_copy(ctx, plan_id)
    with session_scope() as session:
        assert session.scalars(
            select(QuizAttemptRow).where(QuizAttemptRow.position_id == position_id)
        ).all() == []

    graded = coach_tools.evaluate_candidate_move(_ctx("lichess", username), position_id, "e4")
    assert "error" not in graded


def test_monitoring_page_shows_no_coach_text(monkeypatch, tmp_path):
    monkeypatch.setattr(monitoring, "LOG_PATH", tmp_path / "events.jsonl")
    monitoring.log_event(
        "coach_feedback", {"question": "my secret plan", "answer": "a", "rating": "helpful"}
    )
    monitoring.log_event("coach_answered", {"player": "someone", "tools_used": []})
    body = _client().get("/api/monitoring")
    assert "my secret plan" not in body.text
    assert "someone" not in body.text
    assert body.json()["feedback_count"] == 1


# ---------------------------------------------------------------- settings


def test_settings_belong_to_the_signed_in_user():
    assert _client().get("/api/account/settings").status_code == 401
    assert _client().put("/api/account/settings", json={"speak_answers": True}).status_code == 401

    first, second = _client(_user()), _client(_user())
    assert first.get("/api/account/settings").json() == {"speak_answers": False}
    assert first.put("/api/account/settings", json={"speak_answers": True}).status_code == 200
    assert first.get("/api/account/settings").json() == {"speak_answers": True}
    assert second.get("/api/account/settings").json() == {"speak_answers": False}


def test_settings_cannot_change_the_plan():
    user_id = _user()
    response = _client(user_id).put("/api/account/settings", json={"plan": "paid"})
    assert response.status_code == 422
    with session_scope() as session:
        assert session.get_one(UserRow, user_id).plan == "free"


# ---------------------------------------------------------------- linking Chess.com


def _mock_chesscom(monkeypatch, *, status=200, profile=None):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=profile or {})

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return REAL_ASYNC_CLIENT(*args, **kwargs)

    monkeypatch.setattr(account_api.httpx, "AsyncClient", factory)


def test_chesscom_link_needs_sign_in():
    assert _client().post("/api/account/chesscom/code", json={"username": "abc"}).status_code == 401
    assert (
        _client().post("/api/account/chesscom/verify", json={"username": "abc"}).status_code == 401
    )


def test_chesscom_link_needs_the_code_on_the_profile(monkeypatch):
    user_id = _user()
    username = f"cc{uuid4().hex[:10]}"
    client = _client(user_id)
    code = client.post("/api/account/chesscom/code", json={"username": username}).json()["code"]
    assert code == chesscom_code(user_id, username)

    _mock_chesscom(monkeypatch, profile={"location": "Oslo"})
    response = client.post("/api/account/chesscom/verify", json={"username": username})
    assert response.status_code == 422
    assert client.get("/api/auth/me").json()["players"] == []

    # Another user's code does not count.
    _mock_chesscom(monkeypatch, profile={"location": chesscom_code(_user(), username)})
    assert (
        client.post("/api/account/chesscom/verify", json={"username": username}).status_code == 422
    )

    _mock_chesscom(monkeypatch, profile={"location": f"Oslo {code}"})
    assert (
        client.post("/api/account/chesscom/verify", json={"username": username}).status_code == 200
    )
    assert client.get("/api/auth/me").json()["players"] == [
        {"platform": "chess.com", "username": username}
    ]
    params = {"platform": "chess.com", "username": username}
    assert _client().get("/api/repertoire", params=params).status_code == 401


def test_chesscom_player_keeps_its_first_owner(monkeypatch):
    first, second = _user(), _user()
    username = f"cc{uuid4().hex[:10]}"
    with session_scope() as session:
        link_player(session, first, "chess.com", username, "chesscom_profile")
    _mock_chesscom(monkeypatch, profile={"location": chesscom_code(second, username)})
    response = _client(second).post("/api/account/chesscom/verify", json={"username": username})
    assert response.status_code == 409
    params = {"platform": "chess.com", "username": username}
    assert _client(first).get("/api/repertoire", params=params).status_code == 200


def test_chesscom_errors_are_reported(monkeypatch):
    client = _client(_user())
    _mock_chesscom(monkeypatch, status=404)
    assert client.post("/api/account/chesscom/verify", json={"username": "abc"}).status_code == 404
    _mock_chesscom(monkeypatch, status=403)
    assert client.post("/api/account/chesscom/verify", json={"username": "abc"}).status_code == 502
    bad = client.post("/api/account/chesscom/verify", json={"username": "../etc/x"})
    assert bad.status_code == 422


# ---------------------------------------------------------------- coach limit


QUESTION = {"question": "What now?", "platform": "chess.com", "username": "kfctofu"}


def test_free_user_gets_a_clear_429_at_the_limit(monkeypatch):
    monkeypatch.setenv("COACH_DAILY_LIMIT_FREE", "2")
    user_id = _user()
    client = _client(user_id)
    assert client.post("/api/coach/ask", json=QUESTION).status_code == 200
    assert client.post("/api/coach/ask", json=QUESTION).status_code == 200
    assert client.get("/api/auth/me").json()["coach_quota"]["remaining"] == 0

    blocked = client.post("/api/coach/ask", json=QUESTION)
    assert blocked.status_code == 429
    assert "2 coach questions" in blocked.json()["detail"]
    assert "midnight UTC" in blocked.json()["detail"]
    assert 0 < int(blocked.headers["retry-after"]) <= 86401

    # The limit is per user, and a blocked question is not counted.
    assert _client(_user()).post("/api/coach/ask", json=QUESTION).status_code == 200
    assert client.get("/api/auth/me").json()["coach_quota"]["used"] == 2


def test_a_limit_of_zero_does_not_claim_questions_were_used(monkeypatch):
    monkeypatch.setenv("COACH_DAILY_LIMIT_FREE", "0")
    monkeypatch.setenv("COACH_DAILY_LIMIT_ANONYMOUS", "0")

    signed_in = _client(_user()).post("/api/coach/ask", json=QUESTION)
    assert signed_in.status_code == 429
    assert "0 coach questions" not in signed_in.json()["detail"]

    anonymous = TestClient(app).post("/api/coach/ask", json=QUESTION)
    assert anonymous.status_code == 429
    assert "Sign in" in anonymous.json()["detail"]


def test_paid_plan_has_its_own_limit(monkeypatch):
    monkeypatch.setenv("COACH_DAILY_LIMIT_FREE", "0")
    monkeypatch.setenv("COACH_DAILY_LIMIT_PAID", "1")
    assert _client(_user("free")).post("/api/coach/ask", json=QUESTION).status_code == 429
    client = _client(_user("paid"))
    assert client.post("/api/coach/ask", json=QUESTION).status_code == 200
    assert client.post("/api/coach/ask", json=QUESTION).status_code == 429


def test_limit_resets_the_next_utc_day(monkeypatch):
    monkeypatch.setenv("COACH_DAILY_LIMIT_FREE", "1")
    client = _client(_user())
    assert client.post("/api/coach/ask", json=QUESTION).status_code == 200
    assert client.post("/api/coach/ask", json=QUESTION).status_code == 429
    tomorrow = datetime.now(UTC).date() + timedelta(days=1)
    monkeypatch.setattr(coach_limits, "_today", lambda: tomorrow)
    assert client.post("/api/coach/ask", json=QUESTION).status_code == 200


def _anon_client() -> TestClient:
    return TestClient(app, client=(f"10.1.{uuid4().int % 250}.{uuid4().int % 250}", 5000))


def test_anonymous_limit_cannot_be_dodged_with_a_forged_header(monkeypatch):
    monkeypatch.setenv("COACH_DAILY_LIMIT_ANONYMOUS", "1")
    client = _anon_client()
    assert client.post("/api/coach/ask", json=QUESTION).status_code == 200
    forged = client.post(
        "/api/coach/ask", json=QUESTION, headers={"X-Forwarded-For": "203.0.113.9"}
    )
    assert forged.status_code == 429
    assert "Sign in" in forged.json()["detail"]


def test_proxy_address_is_read_from_the_trusted_end_of_the_header(monkeypatch):
    monkeypatch.setenv("COACH_DAILY_LIMIT_ANONYMOUS", "1")
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    client = _anon_client()

    def ask(forwarded_for: str) -> int:
        headers = {"X-Forwarded-For": forwarded_for}
        return client.post("/api/coach/ask", json=QUESTION, headers=headers).status_code

    assert ask("1.1.1.1, 198.51.100.7") == 200
    # What the caller put before the proxy's own entry changes nothing.
    assert ask("2.2.2.2, 198.51.100.7") == 429
    assert ask("192.0.2.8") == 200


def test_failed_answer_gives_the_question_back(monkeypatch):
    async def explode(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(adaptive_api, "ask_coach", explode)
    user_id = _user()
    client = TestClient(app, raise_server_exceptions=False)
    client.cookies.set(SESSION_COOKIE, sign({"uid": user_id}, "session"))
    assert client.post("/api/coach/ask", json=QUESTION).status_code == 500
    assert client.get("/api/auth/me").json()["coach_quota"]["used"] == 0


def test_parallel_questions_cannot_pass_the_limit():
    scope = QuotaScope(f"user:{uuid4().hex}", "free")

    def ask(_index: int) -> bool:
        with session_scope() as session:
            return take_quota(session, scope)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(ask, range(40)))
    assert sum(results) == 20
    with session_scope() as session:
        assert coach_quota(session, scope).used == 20


# ---------------------------------------------------------------- migration


def test_migrations_have_a_single_head():
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    assert len(ScriptDirectory.from_config(config).get_heads()) == 1


def test_account_migration_upgrades_downgrades_and_matches_the_models(tmp_path):
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{tmp_path / 'migrated.db'}"}

    def alembic(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=BACKEND,
            env=env,
            capture_output=True,
            text=True,
        )

    for args in (("upgrade", "head"), ("downgrade", "d4f7b9e2c1a8"), ("upgrade", "head")):
        result = alembic(*args)
        assert result.returncode == 0, result.stdout + result.stderr
    # `check` also reports drift that predates accounts, so look only at the account tables.
    report = alembic("check")
    for table in ("users", "auth_identities", "user_players", "coach_usage"):
        assert table not in report.stdout + report.stderr
