from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from chess_coach_agent import study_plan
from chess_coach_agent.api import app
from chess_coach_agent.db import session_scope
from chess_coach_agent.db_models import (
    CriticalMomentRow,
    GameRow,
    QuizAttemptRow,
    RepertoireMoveRow,
    RepertoireReviewRow,
    RepertoireRow,
    ReviewScheduleRow,
    StudyPlanRow,
    TrainingPlanRow,
    TrainingPositionRow,
)
from chess_coach_agent.insights import Leak, LeakAction
from chess_coach_agent.repositories import get_or_create_player
from chess_coach_agent.study_plan import (
    GameInput,
    PlanInputs,
    RepertoireInput,
    ThemeSupply,
    build_plan,
    local_date,
    verify_rationale,
)
from chess_coach_agent.today_api import DueSummary, ThemeCount
from chess_coach_agent.training import build_due_session

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
OTHER_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
client = TestClient(app)


@pytest.fixture(autouse=True)
def no_llm_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _seed(username: str, games: int = 12, due: int = 3) -> str:
    """Twelve losses with a missed tactic each, three due reviews and a white repertoire."""
    now = datetime.now(UTC)
    with session_scope() as session:
        player = get_or_create_player(session, "lichess", username)
        for number in range(games):
            game = GameRow(
                player_id=player.id,
                external_game_id=f"{username}-g{number}",
                white="me",
                black=f"opp{number}",
                result="0-1",
                player_result="loss",
                player_color="white",
                played_at=f"2026.10.{number + 1:02d}",
                time_control="300",
                metadata_json={"game": {}, "moves": []},
            )
            session.add(game)
            session.flush()
            session.add(
                CriticalMomentRow(
                    game_id=game.id,
                    external_moment_id=f"{username}-g{number}-9",
                    move_number=5,
                    ply=9,
                    phase="middlegame",
                    theme="missed_tactic",
                    played_san="Nf3",
                    best_san="Bb5",
                    fen_before=START_FEN,
                    fen_after=START_FEN,
                    severity=30.0,
                    explanation={"trainable": True},
                )
            )
        plan = TrainingPlanRow(player_id=player.id)
        session.add(plan)
        session.flush()
        for order in range(due):
            position = TrainingPositionRow(
                plan_id=plan.id,
                position_order=order,
                fen=f"{START_FEN[:-1]}{order + 1}",
                correct_move="e4",
                theme="loose_piece",
                difficulty="intermediate",
            )
            session.add(position)
            session.flush()
            session.add(
                ReviewScheduleRow(
                    player_id=player.id,
                    position_id=position.id,
                    due_at=now - timedelta(days=1 + order),
                )
            )
        rep = RepertoireRow(player_id=player.id, color="white", name="White lines")
        session.add(rep)
        session.flush()
        move = RepertoireMoveRow(
            repertoire_id=rep.id,
            parent_fen_epd=" ".join(START_FEN.split(" ")[:4]),
            san="e4",
            uci="e2e4",
            fen_after=" ".join(OTHER_FEN.split(" ")[:4]),
        )
        session.add(move)
        session.flush()
        session.add(RepertoireReviewRow(move_id=move.id, due_at=now - timedelta(hours=1)))
        return player.id


def _tasks(plan: dict) -> list[dict]:
    return [task for day in plan["days"] for task in day["tasks"]]


def _attempt(player_id: str, theme: str, status: str = "active", legal: bool = True, at=None):
    with session_scope() as session:
        training = TrainingPlanRow(player_id=player_id, status=status)
        session.add(training)
        session.flush()
        position = TrainingPositionRow(
            plan_id=training.id,
            position_order=1,
            fen=START_FEN,
            correct_move="e4",
            theme=theme,
            difficulty="intermediate",
        )
        session.add(position)
        session.flush()
        attempt = QuizAttemptRow(
            player_id=player_id,
            position_id=position.id,
            submitted_move="e4",
            correct=False,
            legal=legal,
        )
        if at:
            attempt.created_at = at
        session.add(attempt)


def _leak(theme: str = "missed_tactic", points: float = 2.5) -> Leak:
    return Leak(
        id=f"theme:{theme}",
        title="Missed tactics",
        detail="Detail.",
        points_per_10_games=points,
        sample_size=20,
        action=LeakAction(type="practice", theme=theme, label="Practice"),
    )


def test_build_plan_is_deterministic_and_covers_every_day():
    def inputs() -> PlanInputs:
        return PlanInputs(
            leaks=[_leak()],
            due=DueSummary(count=12, themes=[ThemeCount(theme="loose_piece", count=12)]),
            repertoires=[RepertoireInput("r1", "White lines", "white", 3, 9)],
            games=[GameInput("g1", "bob", "loss", "g1-9", 5, "Nf3", "Bb5")],
            supply=ThemeSupply({"missed_tactic": 8}),
        )

    days = build_plan(inputs())
    assert [t.model_dump() for d in days for t in d] == [
        t.model_dump() for d in build_plan(inputs()) for t in d
    ]
    assert len(days) == 7 and all(days)
    tasks = [task for day in days for task in day]
    assert {task.kind for task in tasks} == {
        "due_review",
        "leak_practice",
        "game_review",
        "repertoire_review",
    }
    assert sum(t.target for t in tasks if t.kind == "due_review") == 12
    assert len({task.id for task in tasks}) == len(tasks)


def test_build_plan_caps_tasks_and_spreads_them():
    days = build_plan(
        PlanInputs(
            leaks=[_leak()],
            due=DueSummary(count=500),
            repertoires=[RepertoireInput("r1", "W", "white", 100, 100)],
            games=[GameInput(f"g{i}", "bob", "loss", "m", 5, "Nf3", "Bb5") for i in range(2)],
            supply=ThemeSupply({"missed_tactic": 8}),
        )
    )
    assert all(1 <= len(day) <= 2 for day in days)


def test_build_plan_with_nothing_is_empty():
    assert build_plan(PlanInputs()) == []


def test_leak_without_stored_positions_uses_puzzles_or_is_skipped():
    # A conversion leak can exist with no endgame moments: mixed mode would drill other themes.
    leak = _leak("endgame_conversion")
    days = build_plan(PlanInputs(leaks=[leak]))
    assert {t.session_mode for d in days for t in d} == {"puzzles"}
    # time_pressure has no puzzles, so only its own stored positions can complete a task.
    assert build_plan(PlanInputs(leaks=[_leak("time_pressure")])) == []
    days = build_plan(
        PlanInputs(leaks=[_leak("time_pressure")], supply=ThemeSupply({"time_pressure": 2}))
    )
    assert {t.target for d in days for t in d} == {2}


def test_opening_leak_builds_or_drills_a_repertoire():
    opening = Leak(
        id="opening",
        title="Bad positions out of the opening",
        detail="Detail.",
        points_per_10_games=1.0,
        sample_size=20,
        action=LeakAction(type="openings", label="Review"),
    )
    assert "repertoire_build" in {
        t.kind for d in build_plan(PlanInputs(leaks=[opening])) for t in d
    }
    days = build_plan(
        PlanInputs(leaks=[opening], repertoires=[RepertoireInput("r1", "W", "white", 0, 4)])
    )
    drill = next(t for d in days for t in d if t.kind == "repertoire_review")
    assert drill.target == 4 and drill.repertoire_color == "white"


def test_get_is_read_only_and_unknown_player_is_not_created():
    assert client.get("/api/study-plan/lichess/nobody-plans").json()["known"] is False
    assert client.post("/api/study-plan/lichess/nobody-plans", json={}).status_code == 404
    assert client.get("/api/study-plan/lichess/nobody-plans").json()["known"] is False
    _seed("plan-readonly", games=1, due=0)
    body = client.get("/api/study-plan/lichess/plan-readonly").json()
    assert body["known"] is True and body["plan"] is None
    with session_scope() as session:
        player = get_or_create_player(session, "lichess", "plan-readonly")
        assert session.query(StudyPlanRow).filter_by(player_id=player.id).count() == 0


def test_post_builds_once_and_links_to_real_data():
    _seed("plan-user")
    first = client.post("/api/study-plan/lichess/Plan-User", json={"today": _today()}).json()
    plan = first["plan"]
    second = client.post("/api/study-plan/lichess/plan-user", json={"today": _today()}).json()
    assert second["plan"]["id"] == plan["id"]
    assert plan["today_index"] == 0
    assert plan["rationale"] is None  # no key, no note
    assert plan["done_tasks"] == 0
    assert len(plan["days"]) == 7 and all(day["tasks"] for day in plan["days"])
    assert "Missed tactics" in plan["summary"]
    tasks = _tasks(plan)
    review = next(t for t in tasks if t["kind"] == "game_review")
    # Newest loss first, linked to the moment the review page opens.
    assert review["game_id"] == "plan-user-g11"
    assert review["moment_id"] == "plan-user-g11-9"
    assert "you played Nf3, Bb5 was better" in review["detail"]
    assert next(t for t in tasks if t["kind"] == "due_review")["target"] == 3
    assert next(t for t in tasks if t["kind"] == "repertoire_review")["target"] == 1
    assert next(t for t in tasks if t["kind"] == "leak_practice")["theme"] == "missed_tactic"


def test_player_with_nothing_to_do_gets_no_plan():
    with session_scope() as session:
        get_or_create_player(session, "lichess", "plan-empty")
    body = client.post("/api/study-plan/lichess/plan-empty", json={}).json()
    assert body["plan"] is None


def test_progress_comes_from_attempts_and_ignores_older_or_illegal_ones():
    player_id = _seed("plan-progress")
    plan = client.post("/api/study-plan/lichess/plan-progress", json={}).json()["plan"]
    before = datetime.now(UTC) - timedelta(days=2)
    _attempt(player_id, "missed_tactic", at=before)
    _attempt(player_id, "missed_tactic", legal=False)
    _attempt(player_id, "king_safety")
    body = client.get("/api/study-plan/lichess/plan-progress").json()["plan"]
    assert sum(t["progress"] for t in _tasks(body) if t["kind"] == "leak_practice") == 0

    for _ in range(7):
        _attempt(player_id, "missed_tactic")
    body = client.get("/api/study-plan/lichess/plan-progress").json()["plan"]
    leaks = [t for t in _tasks(body) if t["kind"] == "leak_practice"]
    # Earliest task fills first, the rest spills into the next one.
    assert [t["progress"] for t in leaks[:2]] == [5, 2]
    assert [t["status"] for t in leaks[:2]] == ["done", "in_progress"]
    assert body["done_tasks"] == 1
    assert body["id"] == plan["id"]


def test_due_session_moves_the_schedule_and_counts_as_review():
    player_id = _seed("plan-due")
    client.post("/api/study-plan/lichess/plan-due", json={})
    created = client.post(
        "/api/training/sessions",
        json={"platform": "lichess", "username": "plan-due", "mode": "due", "position_count": 2},
    ).json()
    assert created["status"] == "review"
    assert len(created["positions"]) == 2
    with session_scope() as session:
        schedules = session.query(ReviewScheduleRow).filter_by(player_id=player_id).all()
        moved = {row.position_id for row in schedules}
        assert len(schedules) == 3  # moved, not duplicated
        assert {item["id"] for item in created["positions"]} <= moved

    position_id = created["positions"][0]["id"]
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
    body = client.get("/api/study-plan/lichess/plan-due").json()["plan"]
    assert next(t for t in _tasks(body) if t["kind"] == "due_review")["progress"] == 1
    # A review attempt does not also tick the theme practice task.
    assert all(t["progress"] == 0 for t in _tasks(body) if t["kind"] == "leak_practice")


def test_answering_a_due_position_clears_it():
    player_id = _seed("plan-clear", due=1)
    with session_scope() as session:
        plan = build_due_session(session, "lichess", "plan-clear")
        position = session.query(TrainingPositionRow).filter_by(plan_id=plan.id).one()
        position_id = position.id
        plan_id = plan.id
    reply = client.post(
        f"/api/training/sessions/{plan_id}/attempts",
        json={"position_id": position_id, "move": "e4"},
    )
    assert reply.status_code == 200
    with session_scope() as session:
        schedule = session.query(ReviewScheduleRow).filter_by(player_id=player_id).one()
        due_at = schedule.due_at if schedule.due_at.tzinfo else schedule.due_at.replace(tzinfo=UTC)
        assert due_at > datetime.now(UTC)


def test_due_mode_with_nothing_due_is_a_normal_session():
    _seed("plan-none-due", games=2, due=0)
    created = client.post(
        "/api/training/sessions",
        json={"platform": "lichess", "username": "plan-none-due", "mode": "due"},
    ).json()
    assert created["status"] == "active"
    assert created["positions"]


def test_repertoire_drill_answers_count_once_per_move():
    _seed("plan-rep")
    client.post("/api/study-plan/lichess/plan-rep", json={})
    reps = client.get(
        "/api/repertoire", params={"platform": "lichess", "username": "plan-rep"}
    ).json()
    rep_id = reps[0]["id"]
    item = client.get(f"/api/repertoire/{rep_id}/drill").json()["items"][0]
    for _ in range(2):
        reply = client.post(
            f"/api/repertoire/{rep_id}/drill/answer", json={"move_id": item["move_id"], "move": "e4"}
        )
        assert reply.status_code == 200
    body = client.get("/api/study-plan/lichess/plan-rep").json()["plan"]
    task = next(t for t in _tasks(body) if t["kind"] == "repertoire_review")
    assert task["progress"] == 1 and task["status"] == "done"


def test_game_retry_completes_the_review_and_is_validated():
    _seed("plan-game")
    plan = client.post("/api/study-plan/lichess/plan-game", json={}).json()["plan"]
    game_id = next(t for t in _tasks(plan) if t["kind"] == "game_review")["game_id"]
    url = "/api/study-plan/lichess/plan-game/game-retry"
    assert client.post(url, json={"game_id": "not-mine", "ply": 9}).status_code == 404
    assert client.post(url, json={"game_id": game_id, "ply": 9}).status_code == 200
    body = client.get("/api/study-plan/lichess/plan-game").json()["plan"]
    task = next(t for t in _tasks(body) if t["game_id"] == game_id)
    assert task["status"] == "done"


def test_retried_games_are_not_offered_again():
    player_id = _seed("plan-next")
    client.post(
        "/api/study-plan/lichess/plan-next/game-retry", json={"game_id": "plan-next-g11", "ply": 9}
    )
    with session_scope() as session:
        games = study_plan._games_to_review(session, player_id)
    assert [game.game_id for game in games] == ["plan-next-g10", "plan-next-g9"]


def test_days_overdue_expiry_and_next_plan():
    _seed("plan-week")
    plan = client.post("/api/study-plan/lichess/plan-week", json={}).json()["plan"]
    with session_scope() as session:
        row = session.get(StudyPlanRow, plan["id"])
        row.start_date = (date.fromisoformat(row.start_date) - timedelta(days=1)).isoformat()
    body = client.get("/api/study-plan/lichess/plan-week").json()["plan"]
    assert body["today_index"] == 1
    assert {t["status"] for t in body["days"][0]["tasks"]} == {"overdue"}
    assert {t["status"] for t in body["days"][1]["tasks"]} == {"todo"}

    with session_scope() as session:
        row = session.get(StudyPlanRow, plan["id"])
        row.start_date = (date.fromisoformat(row.start_date) - timedelta(days=6)).isoformat()
    body = client.get("/api/study-plan/lichess/plan-week").json()
    assert body["plan"] is None
    assert body["last_plan"]["total_tasks"] == plan["total_tasks"]
    fresh = client.post("/api/study-plan/lichess/plan-week", json={}).json()
    assert fresh["plan"]["id"] != plan["id"]


def test_local_date_is_trusted_only_near_utc():
    now = datetime(2026, 10, 31, 12, tzinfo=UTC)
    assert local_date("2026-11-01", now) == date(2026, 11, 1)
    assert local_date("2026-10-30", now) == date(2026, 10, 30)
    assert local_date("2027-01-01", now) == now.date()
    assert local_date("garbage", now) == now.date()
    assert local_date(None, now) == now.date()


FACTS = {
    "leaks": [{"title": "Missed tactics", "points_per_10_games": 2.5, "games": 40}],
    "due_positions": 12,
    "repertoire_moves_due": 0,
    "games_to_review": 2,
    "days": 7,
    "tasks": 9,
}


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("Missed tactics cost you 2.5 points per 10 games. Clear the 12 due positions.", True),
        ("Missed tactics cost you 3 points per 10 games.", False),
        ("Missed tactics cost you 2.5 points across 40 games, so clear 12 positions first.", True),
        ("Tactics are the priority this week.", True),
        ("You will gain 100 rating points.", False),
        ("Play Nf3 more often.", False),
        ("Watch the e4 pawn.", False),
        ("Castle with O-O sooner.", False),
        ("", False),
        ("word " * 100, False),
    ],
)
def test_verify_rationale(text, ok):
    assert verify_rationale(text, FACTS) is ok


def _fake_llm(monkeypatch, reply: str, used: bool = True) -> None:
    async def fake(system, prompt, temperature=0.0):
        assert "Missed tactics" in prompt
        return reply, used

    monkeypatch.setattr(study_plan, "complete_with_openrouter", fake)


def test_write_rationale_rejects_ungrounded_or_broken_output(monkeypatch):
    _fake_llm(monkeypatch, '{"rationale": "Tactics cost you 2.5 points per 10 games."}')
    assert asyncio.run(study_plan.write_rationale(FACTS))[0].startswith("Tactics")
    _fake_llm(monkeypatch, '{"rationale": "Tactics cost you 9.9 points."}')
    assert asyncio.run(study_plan.write_rationale(FACTS))[0] is None
    _fake_llm(monkeypatch, "no json here")
    assert asyncio.run(study_plan.write_rationale(FACTS))[0] is None
    _fake_llm(monkeypatch, "", used=False)
    assert asyncio.run(study_plan.write_rationale(FACTS))[0] is None


def test_post_stores_a_verified_rationale_only_with_a_key(monkeypatch):
    _seed("plan-note")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    _fake_llm(monkeypatch, '{"rationale": "Missed tactics come first this week."}')
    plan = client.post("/api/study-plan/lichess/plan-note", json={}).json()["plan"]
    assert plan["rationale"] == "Missed tactics come first this week."


def test_post_survives_a_rejected_rationale(monkeypatch):
    _seed("plan-bad-note")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    _fake_llm(monkeypatch, '{"rationale": "Missed tactics cost 99 points."}')
    plan = client.post("/api/study-plan/lichess/plan-bad-note", json={}).json()["plan"]
    assert plan["rationale"] is None
    assert plan["summary"]
