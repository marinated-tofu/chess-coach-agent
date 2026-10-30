import uuid

import chess
import pytest
from fastapi.testclient import TestClient

from chess_coach_agent import engine, time_trainer
from chess_coach_agent.api import app
from chess_coach_agent.db import init_db, session_scope
from chess_coach_agent.db_models import GameRow, QuizAttemptRow, TrainingPositionRow
from chess_coach_agent.engine import EngineLine, LineScore, PositionEval
from chess_coach_agent.repositories import get_or_create_player, training_session_view
from chess_coach_agent.time_trainer import (
    TimeTrainerUnavailable,
    build_time_session,
    candidates_from_moves,
    countdown_seconds,
    position_key,
)
from chess_coach_agent.training import evaluate_attempt

needs_stockfish = pytest.mark.skipif(not engine.stockfish_path(), reason="Stockfish not installed")

# White to move and the e5 knight can take the undefended queen on d7; Nf3-g1 throws that away.
CRITICAL_FEN = "r1b1kb1r/pppq1ppp/2n2n2/3pN3/3P4/2N5/PPP1PPPP/R1BQKB1R w KQkq - 0 6"
# Quiet Ruy/Italian tabiya: several white moves are about equal.
SIMPLE_FEN = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3"


def _move(**fields):
    return {
        "color": "white",
        "san": "a3",
        "uci": "a2a3",
        "move_number": 10,
        "time_spent_seconds": 8.0,
        "win_pct_loss": 1.0,
        "classification": "good",
        **fields,
    }


def _filler(count=10, seconds=8.0):
    return [_move(time_spent_seconds=seconds) for _ in range(count)]


def _rushed_move(fen=CRITICAL_FEN, **fields):
    return _move(
        fen_before=fen,
        san="Nf3",
        uci="e5f3",
        best_san="Nxd7",
        time_spent_seconds=2.0,
        win_pct_loss=30.0,
        classification="blunder",
        **fields,
    )


def _burned_move(fen=SIMPLE_FEN, **fields):
    return _move(
        fen_before=fen,
        san="Bc4",
        uci="f1c4",
        best_san="Bb5",
        time_spent_seconds=45.0,
        win_pct_loss=0.5,
        **fields,
    )


def _seed_game(session, player, moves, time_control="300"):
    session.add(
        GameRow(
            player_id=player.id,
            external_game_id=uuid.uuid4().hex,
            white=player.username,
            black="rival",
            result="0-1",
            player_result="loss",
            player_color="white",
            played_at="2026.06.20",
            time_control=time_control,
            metadata_json={"moves": moves},
        )
    )
    session.flush()


def _player(session, prefix="clock"):
    return get_or_create_player(session, "lichess", f"{prefix}-{uuid.uuid4().hex[:10]}")


def test_rushed_and_burned_moves_are_nominated_against_the_games_own_pace():
    moves = [*_filler(), _rushed_move(), _burned_move()]
    found = candidates_from_moves(moves, "white", "300", "rival", "2026.06.20")
    assert [(item.kind, item.played_san) for item in found] == [
        ("rushed", "Nf3"),
        ("burned", "Bc4"),
    ]
    assert found[0].typical_seconds == 8.0
    assert found[0].opponent == "rival"


def test_moves_that_are_not_clock_errors_are_ignored():
    not_candidates = [
        # A fast mistake in time trouble was forced by the clock.
        _rushed_move(time_pressure=True),
        # A book move is not a decision about time.
        {**_rushed_move(), "classification": "book"},
        # A slow move that blundered is not time wasted in a simple position.
        {**_burned_move(), "win_pct_loss": 30.0},
        # Fast and fine.
        {**_rushed_move(), "win_pct_loss": 2.0},
        # Long, but within the usual pace for this game.
        {**_burned_move(), "time_spent_seconds": 12.0},
        # The opponent's clock is not the player's.
        {**_rushed_move(), "color": "black"},
    ]
    assert candidates_from_moves([*_filler(), *not_candidates], "white", "300") == []


def test_games_without_usable_clocks_are_not_clock_games():
    assert candidates_from_moves(_filler(), "white", "") is None
    assert candidates_from_moves(_filler(), "white", "1/259200") is None
    assert candidates_from_moves(_filler(3), "white", "300") is None
    no_times = [_move(time_spent_seconds=None) for _ in range(12)]
    assert candidates_from_moves(no_times, "white", "300") is None


def test_countdown_follows_the_position_and_the_players_pace():
    blunder = countdown_seconds("rushed", 8.0, 300, 0.6)
    mistake = countdown_seconds("rushed", 8.0, 300, 0.2)
    assert blunder > mistake > countdown_seconds("burned", 8.0, 300)
    assert countdown_seconds("rushed", 8.0, 300, 0.6) == 26
    # Capped at a tenth of the base clock, floored for reading a cold board.
    assert countdown_seconds("rushed", 60.0, 300, 1.0) == 30
    assert countdown_seconds("rushed", 60.0, 7200, 1.0) == 90
    assert countdown_seconds("rushed", 1.0, 60, 0.3) == 15
    assert countdown_seconds("burned", 2.0, 60) == 8
    assert countdown_seconds("burned", 40.0, 900) == 20


def test_same_position_on_a_later_move_number_counts_once():
    a = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3"
    b = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 6 5"
    assert position_key(a) == position_key(b)


def test_status_distinguishes_no_clock_data_from_nothing_to_train():
    init_db()
    with TestClient(app) as client:
        unknown = client.get(f"/api/library/lichess/nobody-{uuid.uuid4().hex[:8]}/time-trainer")
        assert unknown.status_code == 200
        assert unknown.json()["status"] == "no_clock_data"

        with session_scope() as session:
            old_import = _player(session, "noclock")
            _seed_game(session, old_import, [_move(time_spent_seconds=None) for _ in range(12)])
            steady = _player(session, "steady")
            _seed_game(session, steady, _filler())
            active = _player(session, "active")
            _seed_game(session, active, [*_filler(), _rushed_move(), _burned_move()])
            names = old_import.username, steady.username, active.username

        def status(name):
            return client.get(f"/api/library/lichess/{name}/time-trainer").json()

        assert status(names[0])["status"] == "no_clock_data"
        assert status(names[1])["status"] == "no_candidates"
        assert status(names[1])["clock_games"] == 1
        ready = status(names[2])
        assert ready["status"] == "ready"
        assert (ready["rushed_count"], ready["burned_count"]) == (1, 1)


def test_session_is_refused_without_stockfish(monkeypatch):
    monkeypatch.setattr(time_trainer, "stockfish_path", lambda: None)
    init_db()
    with session_scope() as session:
        player = _player(session, "noengine")
        _seed_game(session, player, [*_filler(), _rushed_move()])
        with pytest.raises(TimeTrainerUnavailable):
            build_time_session(session, player.platform, player.username)


class _HeuristicAnalyzer:
    """What EngineAnalyzer returns when Stockfish dies part way through."""

    def evaluate(self, board, multipv=2):
        move = next(iter(board.legal_moves))
        return PositionEval(lines=(LineScore(move=move, value=0, cp=0),), heuristic=True)


def test_heuristic_scores_never_become_positions():
    init_db()
    with session_scope() as session:
        player = _player(session, "fallback")
        _seed_game(session, player, [*_filler(), _rushed_move(), _burned_move()])
        plan = build_time_session(
            session, player.platform, player.username, analyzer=_HeuristicAnalyzer()
        )
        assert plan is None


@needs_stockfish
def test_session_positions_carry_real_engine_data_and_hide_the_answer():
    init_db()
    with session_scope() as session:
        player = _player(session, "session")
        _seed_game(session, player, [*_filler(), _rushed_move(), _burned_move()])
        plan = build_time_session(session, player.platform, player.username)
        assert plan is not None and plan.focus_themes == ["time_management"]
        rows = session.query(TrainingPositionRow).filter_by(plan_id=plan.id).all()
        by_kind = {row.timing["kind"]: row for row in rows}
        assert set(by_kind) == {"rushed", "burned"}

        critical = by_kind["rushed"]
        assert critical.correct_move == "Nxd7"
        assert critical.timing["played_win_pct_loss"] >= 10
        assert critical.timing["played_verdict"] in ("mistake", "blunder")
        assert critical.timing["budget_seconds"] > by_kind["burned"].timing["budget_seconds"]
        assert critical.choices == [] and critical.hint is None

        view = training_session_view(session, plan.id)
        payload = view.model_dump()
        for position in payload["positions"]:
            assert position["time_budget_seconds"] > 0
            assert position["prompt"] == time_trainer.TIME_PROMPT
            assert position["theme"] == "time_management"
            assert "timing" not in position and "explanation" not in position


@needs_stockfish
def test_best_move_in_time_shows_both_clocks_and_the_verdict():
    init_db()
    with session_scope() as session:
        player = _player(session, "grade")
        _seed_game(session, player, [*_filler(), _rushed_move()])
        plan = build_time_session(session, player.platform, player.username)
        row = session.query(TrainingPositionRow).filter_by(plan_id=plan.id).one()

        result = evaluate_attempt(session, row.id, "Nxd7", elapsed_ms=6400)
        assert result.correct and result.legal
        timing = result.time_result
        assert timing.verdict == "best" and not timing.timed_out
        assert (timing.original_seconds, timing.attempt_seconds) == (2.0, 6.4)
        assert timing.played_san == "Nf3" and timing.played_verdict in ("mistake", "blunder")
        assert timing.opponent == "rival" and timing.move_number == 10

        again = evaluate_attempt(session, row.id, "a3", elapsed_ms=3000)
        assert not again.correct
        assert again.time_result.verdict in ("mistake", "blunder")
        assert again.time_result.win_pct_loss >= 10


@needs_stockfish
def test_mating_move_is_graded_as_best():
    # Back-rank mate: the after-position is game over, which the engine still has to score.
    fen = "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1"
    init_db()
    with session_scope() as session:
        player = _player(session, "mate")
        _seed_game(session, player, [*_filler(), _rushed_move()])
        plan = build_time_session(session, player.platform, player.username)
        row = session.query(TrainingPositionRow).filter_by(plan_id=plan.id).one()
        row.fen, row.correct_move = fen, "Rd8#"
        session.flush()
        result = evaluate_attempt(session, row.id, "Rd8#", elapsed_ms=1000)
        assert result.correct and result.time_result.verdict == "best"


@needs_stockfish
def test_flagging_records_a_miss_without_grading_a_move():
    init_db()
    with session_scope() as session:
        player = _player(session, "flag")
        _seed_game(session, player, [*_filler(), _rushed_move()])
        plan = build_time_session(session, player.platform, player.username)
        row = session.query(TrainingPositionRow).filter_by(plan_id=plan.id).one()
        budget = row.timing["budget_seconds"]

        flagged = evaluate_attempt(session, row.id, "", elapsed_ms=budget * 1000, timed_out=True)
        assert flagged.legal and not flagged.correct and flagged.cp_loss is None
        assert flagged.time_result.verdict == "timed_out"
        assert flagged.best_move == "Nxd7" and "Time ran out" in flagged.explanation
        assert session.query(QuizAttemptRow).filter_by(position_id=row.id).one().correct is False

        # A move sent well after zero is a flag too, however good it is.
        late = evaluate_attempt(session, row.id, "Nxd7", elapsed_ms=(budget + 5) * 1000)
        assert not late.correct and late.time_result.timed_out


def test_verdict_is_unavailable_rather_than_invented_when_the_engine_is_gone(monkeypatch):
    class FallbackAnalyzer:
        def analyse(self, board, pov):
            return EngineLine(best_move=None, score_cp=0, engine_backed=False)

        def close(self):
            pass

    monkeypatch.setattr("chess_coach_agent.training.EngineAnalyzer", FallbackAnalyzer)
    init_db()
    with session_scope() as session:
        player = _player(session, "gone")
        _seed_game(session, player, _filler())
        plan_id = _manual_plan(session, player)
        row = session.query(TrainingPositionRow).filter_by(plan_id=plan_id).one()
        result = evaluate_attempt(session, row.id, "Nxd7", elapsed_ms=1000)
        assert result.time_result.verdict == "unavailable"
        assert result.cp_loss is None and result.time_result.win_pct_loss is None
        assert result.correct  # still the stored best move
        wrong = evaluate_attempt(session, row.id, "a3", elapsed_ms=1000)
        assert wrong.time_result.verdict == "unavailable" and not wrong.correct


def test_engine_top_move_costs_nothing_and_near_equal_moves_are_not_called_best(monkeypatch):
    class DisagreeingSearches:
        """The after-search reads lower than the before-search, as real depth 9 can."""

        def __init__(self):
            self.calls = 0

        def analyse(self, board, pov):
            self.calls += 1
            return EngineLine(best_move=None, score_cp=300 if self.calls % 2 else 270)

        def close(self):
            pass

    monkeypatch.setattr("chess_coach_agent.training.EngineAnalyzer", DisagreeingSearches)
    init_db()
    with session_scope() as session:
        player = _player(session, "noise")
        row = session.query(TrainingPositionRow).filter_by(plan_id=_manual_plan(session, player)).one()

        own_pick = evaluate_attempt(session, row.id, "Nxd7", elapsed_ms=1000)
        assert own_pick.time_result.verdict == "best"
        assert own_pick.cp_loss == 0 and own_pick.time_result.win_pct_loss == 0

        other = evaluate_attempt(session, row.id, "a3", elapsed_ms=1000)
        assert other.time_result.verdict == "good" and other.correct
        assert other.cp_loss == 0.3


def _manual_plan(session, player):
    from chess_coach_agent.db_models import TrainingPlanRow

    plan = TrainingPlanRow(
        player_id=player.id, focus_themes=["time_management"], difficulty="intermediate"
    )
    session.add(plan)
    session.flush()
    session.add(
        TrainingPositionRow(
            plan_id=plan.id,
            position_order=1,
            fen=CRITICAL_FEN,
            correct_move="Nxd7",
            choices=[],
            theme="time_management",
            difficulty="intermediate",
            source="game",
            timing={
                "kind": "rushed",
                "budget_seconds": 20,
                "original_seconds": 2.0,
                "typical_seconds": 8.0,
                "played_san": "Nf3",
                "played_verdict": "blunder",
                "played_win_pct_loss": 30.0,
                "move_number": 10,
                "opponent": "rival",
                "played_at": "2026.06.20",
            },
        )
    )
    session.flush()
    return plan.id


class _LevelAnalyzer:
    """Stockfish stand-in: the top two moves are exactly equal, so every position is simple."""

    def evaluate(self, board, multipv=2):
        moves = list(board.legal_moves)[:2]
        return PositionEval(lines=tuple(LineScore(move=m, value=0, cp=0) for m in moves))


def test_repeat_sessions_prefer_positions_not_seen_yet():
    init_db()
    with session_scope() as session:
        player = _player(session, "repeat")
        other = "r1bqkb1r/pppp1ppp/2n2n2/4p3/4P3/2N2N2/PPPP1PPP/R1BQKB1R w KQkq - 4 4"
        _seed_game(session, player, [*_filler(), _burned_move(), _burned_move(fen=other)])
        fake = _LevelAnalyzer()
        first = build_time_session(
            session, player.platform, player.username, position_count=1, analyzer=fake
        )
        second = build_time_session(
            session, player.platform, player.username, position_count=1, analyzer=fake
        )
        fens = [
            session.query(TrainingPositionRow).filter_by(plan_id=plan.id).one().fen
            for plan in (first, second)
        ]
        assert set(fens) == {SIMPLE_FEN, other}


@needs_stockfish
def test_time_mode_through_the_practice_api(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    init_db()
    with session_scope() as session:
        player = _player(session, "api")
        _seed_game(session, player, [*_filler(), _rushed_move(), _burned_move()])
        username = player.username

    body = {"platform": "lichess", "username": username, "mode": "time"}
    with TestClient(app) as client:
        created = client.post("/api/training/sessions", json=body)
        assert created.status_code == 200, created.text
        payload = created.json()
        assert len(payload["positions"]) == 2
        position = payload["positions"][0]
        attempt = client.post(
            f"/api/training/sessions/{payload['id']}/attempts",
            json={
                "position_id": position["id"],
                "move": "",
                "elapsed_ms": position["time_budget_seconds"] * 1000,
                "timed_out": True,
            },
        )
        assert attempt.status_code == 200, attempt.text
        assert attempt.json()["time_result"]["verdict"] == "timed_out"

        empty = client.post(
            "/api/training/sessions",
            json={**body, "username": f"nobody-{uuid.uuid4().hex[:8]}"},
        )
        assert empty.status_code == 409


def test_regular_positions_have_no_time_data(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with TestClient(app) as client:
        response = client.post(
            "/api/training/sessions",
            json={
                "platform": "lichess",
                "username": f"plain-{uuid.uuid4().hex[:8]}",
                "position_count": 1,
                "mode": "puzzles",
            },
        )
        assert response.status_code == 200
        position = response.json()["positions"][0]
        assert position["time_budget_seconds"] is None
        attempt = client.post(
            f"/api/training/sessions/{response.json()['id']}/attempts",
            json={"position_id": position["id"], "move": "a3", "timed_out": True},
        )
        assert attempt.status_code == 200
        assert attempt.json()["time_result"] is None


def test_critical_fixture_really_hangs_a_queen():
    board = chess.Board(CRITICAL_FEN)
    assert board.parse_san("Nxd7").to_square == chess.D7
