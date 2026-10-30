import uuid

import chess
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from chess_coach_agent.api import app
from chess_coach_agent.db import session_scope
from chess_coach_agent.db_models import (
    PlayerMemoryRow,
    QuizAttemptRow,
    ReviewScheduleRow,
    TrainingPlanRow,
    TrainingPositionRow,
)
from chess_coach_agent.puzzles import (
    COACH_THEMES,
    Puzzle,
    check_line,
    filter_puzzles,
    load_puzzles,
)
from chess_coach_agent.repositories import get_or_create_player, recompute_player_memory
from chess_coach_agent.training import build_training_session

# White mates on the back rank with Re8#, and Rd8# is an equally good finish the data omits.
MATE = Puzzle(
    id="mate1",
    fen="6k1/5ppp/8/8/8/8/5PPP/3RR1K1 w - - 0 1",
    solution=("e1e8",),
    solution_san="Re8#",
    rating=800,
    theme="king_safety",
)


def _multi_move() -> Puzzle:
    return next(item for item in load_puzzles() if len(item.solution) >= 3)


def _wrong_move(puzzle: Puzzle) -> str:
    board = chess.Board(puzzle.fen)
    for move in board.legal_moves:
        board.push(move)
        mate = board.is_checkmate()
        board.pop()
        if move.uci() != puzzle.solution[0] and not mate:
            return move.uci()
    raise AssertionError("no wrong move")


def _player() -> dict:
    return {"platform": "lichess", "username": f"puzzler-{uuid.uuid4().hex[:10]}"}


def test_filter_is_strict_about_theme_and_range_and_sorts_easiest_first():
    matches = filter_puzzles("fork-free-nonsense", 1000, 1200)
    assert {item.theme for item in matches} == set(COACH_THEMES)
    themed = filter_puzzles("loose_pieces", 1000, 1200)  # player-side alias
    assert themed and {item.theme for item in themed} == {"loose_piece"}
    assert all(1000 <= item.rating <= 1200 for item in themed)
    assert [item.rating for item in themed] == sorted(item.rating for item in themed)
    assert filter_puzzles(None, 3500, 3600) == []


def test_check_line_walks_the_solution_then_solves():
    puzzle = _multi_move()
    first = check_line(puzzle, puzzle.solution[:1])
    assert (first.status, first.reply) == ("continue", puzzle.solution[1])
    assert check_line(puzzle, puzzle.solution).status == "solved"
    assert check_line(puzzle, [_wrong_move(puzzle)]).status == "wrong"


def test_check_line_accepts_any_mate_and_rejects_impossible_lines():
    assert check_line(MATE, ["d1d8"]).status == "solved"
    puzzle = _multi_move()
    for line in ([], ["e1e1"], puzzle.solution[:2], [_wrong_move(puzzle), puzzle.solution[1], puzzle.solution[2]]):
        with pytest.raises(ValueError):
            check_line(puzzle, line)


def test_catalog_and_listing_do_not_leak_solutions():
    with TestClient(app) as client:
        catalog = client.get("/api/puzzles/catalog").json()
        page = client.get(
            "/api/puzzles",
            params={"theme": "missed_tactic", "min_rating": 1200, "max_rating": 1400, "limit": 5},
        ).json()
        next_page = client.get(
            "/api/puzzles",
            params={"theme": "missed_tactic", "min_rating": 1200, "max_rating": 1400, "limit": 5, "offset": 5},
        ).json()
    assert catalog["total"] == sum(item["count"] for item in catalog["themes"])
    assert [item["theme"] for item in catalog["themes"]] == list(COACH_THEMES)
    assert page["total"] > 5 and len(page["puzzles"]) == 5
    assert "solution" not in page["puzzles"][0]
    assert page["puzzles"][0]["theme_label"] == "Tactics"
    assert not {item["id"] for item in page["puzzles"]} & {item["id"] for item in next_page["puzzles"]}


def test_playing_a_puzzle_through_counts_once_toward_mastery():
    puzzle = _multi_move()
    who = _player()
    url = f"/api/puzzles/{puzzle.id}/moves"
    with TestClient(app) as client:
        reply = client.post(url, json={**who, "line": list(puzzle.solution[:1])}).json()
        assert reply["status"] == "continue" and reply["finish"] is None
        done = client.post(url, json={**who, "line": list(puzzle.solution), "elapsed_ms": 900}).json()
        listed = client.get("/api/puzzles", params={"theme": puzzle.theme, **who, "limit": 60,
                                                    "min_rating": puzzle.rating, "max_rating": puzzle.rating})
    assert done["status"] == "solved"
    finish = done["finish"]
    assert finish["recorded"] is True and finish["streak"] == 1
    assert finish["next_review_at"]
    assert finish["url"].endswith(puzzle.id)
    assert "short" not in finish["tags"] and finish["solution_san"][0] == puzzle.solution_san
    status = {item["id"]: item["status"] for item in listed.json()["puzzles"]}
    assert status[puzzle.id] == "solved"
    with session_scope() as session:
        player = get_or_create_player(session, who["platform"], who["username"])
        attempts = session.scalars(select(QuizAttemptRow).where(QuizAttemptRow.player_id == player.id)).all()
        assert [(item.correct, item.elapsed_ms) for item in attempts] == [(True, 900)]
        position = session.get(TrainingPositionRow, attempts[0].position_id)
        assert (position.source, position.puzzle_id) == ("puzzle", puzzle.id)


def test_a_miss_counts_but_retries_and_reveals_do_not():
    puzzle = _multi_move()
    who = _player()
    url = f"/api/puzzles/{puzzle.id}/moves"
    with TestClient(app) as client:
        wrong = client.post(url, json={**who, "line": [_wrong_move(puzzle)]}).json()
        retry = client.post(url, json={**who, "line": list(puzzle.solution), "record": False}).json()
        reveal = client.post(f"/api/puzzles/{puzzle.id}/reveal", json={**who, "record": False}).json()
    assert wrong["status"] == "wrong" and wrong["finish"]["recorded"] is True
    assert retry["status"] == "solved" and retry["finish"]["recorded"] is False
    assert reveal["recorded"] is False and reveal["solution"] == list(puzzle.solution)
    with session_scope() as session:
        player = get_or_create_player(session, who["platform"], who["username"])
        attempts = session.scalars(select(QuizAttemptRow).where(QuizAttemptRow.player_id == player.id)).all()
        assert [item.correct for item in attempts] == [False]


def test_a_first_look_at_the_solution_is_a_miss():
    puzzle = _multi_move()
    who = _player()
    with TestClient(app) as client:
        reveal = client.post(f"/api/puzzles/{puzzle.id}/reveal", json=who).json()
    assert reveal["recorded"] is True and reveal["streak"] == 0


def test_anonymous_attempts_grade_without_recording_and_bad_input_is_rejected():
    puzzle = _multi_move()
    url = f"/api/puzzles/{puzzle.id}/moves"
    with TestClient(app) as client:
        anonymous = client.post(url, json={"line": list(puzzle.solution)}).json()
        illegal = client.post(url, json={"line": ["a1a1"]})
        missing = client.post("/api/puzzles/nope/moves", json={"line": ["e2e4"]})
    assert anonymous["status"] == "solved" and anonymous["finish"]["recorded"] is False
    assert illegal.status_code == 422
    assert missing.status_code == 404


def test_puzzle_attempts_reuse_one_position_build_streaks_and_stay_out_of_due():
    puzzle = _multi_move()
    who = _player()
    url = f"/api/puzzles/{puzzle.id}/moves"
    with TestClient(app) as client:
        streaks = [
            client.post(url, json={**who, "line": list(puzzle.solution)}).json()["finish"]["streak"]
            for _ in range(3)
        ]
        wrong_puzzle = next(item for item in load_puzzles() if item.id != puzzle.id)
        client.post(
            f"/api/puzzles/{wrong_puzzle.id}/moves", json={**who, "line": [_wrong_move(wrong_puzzle)]}
        )
    assert streaks == [1, 2, 3]
    with session_scope() as session:
        player = get_or_create_player(session, who["platform"], who["username"])
        plans = session.scalars(select(TrainingPlanRow).where(TrainingPlanRow.player_id == player.id)).all()
        assert [plan.status for plan in plans] == ["library"]
        schedules = session.scalars(
            select(ReviewScheduleRow).where(ReviewScheduleRow.player_id == player.id)
        ).all()
        assert len(schedules) == 2
        for schedule in schedules:  # even past their review date, nothing would serve them again
            schedule.due_at = schedule.due_at.replace(year=2020)
        session.flush()
        recompute_player_memory(session, player.id)
        memory = session.get(PlayerMemoryRow, player.id)
        assert memory.mastered_positions == 1
        assert memory.due_positions == 0
        assert memory.quiz_accuracy == {}  # puzzles do not measure transfer from real games
        # Puzzles seen on the page are not repeated in a puzzle practice session.
        session_plan = build_training_session(
            session, who["platform"], who["username"], theme=puzzle.theme, position_count=3, mode="puzzles"
        )
        served = session.scalars(
            select(TrainingPositionRow.puzzle_id).where(TrainingPositionRow.plan_id == session_plan.id)
        ).all()
        assert served and puzzle.id not in served
