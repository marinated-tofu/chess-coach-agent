import uuid

import chess
from fastapi.testclient import TestClient

from chess_coach_agent import engine
from chess_coach_agent.api import app
from chess_coach_agent.db import init_db, session_scope
from chess_coach_agent.db_models import (
    CriticalMomentRow,
    GameRow,
    TrainingPositionRow,
)
from chess_coach_agent.puzzles import (
    COACH_THEMES,
    PUZZLE_PATH,
    load_puzzles,
    map_lichess_themes,
    normalize_theme,
    select_puzzles,
)
from chess_coach_agent.repositories import get_or_create_player, training_session_view
from chess_coach_agent.training import build_training_session, evaluate_attempt

# Real row from the Lichess puzzle database (puzzle 00008), CSV columns:
# PuzzleId,FEN,Moves,Rating,RatingDeviation,Popularity,NbPlays,Themes,...
LICHESS_ROW = {
    "PuzzleId": "00008",
    "FEN": "r6k/pp2r2p/4Rp1Q/3p4/8/1N1P2R1/PqP2bPP/7K b - - 0 24",
    "Moves": "f2g3 e6e7 b2b1 b3c1 b1c1 h6c1",
    "Rating": "1913",
    "RatingDeviation": "75",
    "Popularity": "94",
    "NbPlays": "7000",
    "Themes": "crushing hangingPiece long middlegame",
}


def _load_script():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "build_puzzle_subset.py"
    spec = importlib.util.spec_from_file_location("build_puzzle_subset", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _player(session, prefix="puzzle"):
    player = get_or_create_player(session, "chess.com", f"{prefix}-{uuid.uuid4().hex[:12]}")
    player.current_rating = 1450
    return player


def test_subset_loads_with_every_theme_and_valid_positions():
    puzzles = load_puzzles()
    assert PUZZLE_PATH.stat().st_size < 1_500_000
    assert len(puzzles) >= 1000
    assert len({item.id for item in puzzles}) == len(puzzles)
    counts = {theme: sum(item.theme == theme for item in puzzles) for theme in COACH_THEMES}
    assert all(count >= 200 for count in counts.values()), counts
    assert min(item.rating for item in puzzles) >= 600
    assert max(item.rating for item in puzzles) < 2200
    for item in puzzles[::25]:
        board = chess.Board(item.fen)
        move = chess.Move.from_uci(item.solution[0])
        assert move in board.legal_moves
        assert board.san(move) == item.solution_san


def test_lichess_theme_mapping_priority_and_aliases():
    assert map_lichess_themes(["fork", "middlegame"]) == "missed_tactic"
    assert map_lichess_themes(["hangingPiece", "opening"]) == "loose_piece"
    assert map_lichess_themes(["mateIn1", "rookEndgame"]) == "endgame_conversion"
    assert map_lichess_themes(["kingsideAttack", "mateIn2", "middlegame"]) == "king_safety"
    assert map_lichess_themes(["opening", "advantage"]) == "opening_drift"
    assert map_lichess_themes(["advantage", "middlegame", "short"]) is None
    assert normalize_theme("loose_pieces") == "loose_piece"
    assert normalize_theme("time_pressure") is None


def test_lichess_first_move_is_the_opponents_move():
    puzzle = _load_script().convert_row(LICHESS_ROW)
    assert puzzle is not None
    # The stored position is after Black's Bxg3; White to move and find Rxe7.
    board = chess.Board(LICHESS_ROW["FEN"])
    board.push_uci("f2g3")
    assert puzzle["fen"] == board.fen()
    assert chess.Board(puzzle["fen"]).turn == chess.WHITE
    assert puzzle["solution"] == ["e6e7", "b2b1", "b3c1", "b1c1", "h6c1"]
    assert puzzle["solution_san"] == "Rxe7"
    assert puzzle["theme"] == "loose_piece"
    assert puzzle["rating"] == 1913


def test_select_puzzles_by_theme_rating_and_excludes_repeats():
    pool = load_puzzles()
    first = select_puzzles("missed_tactic", 1450, 5, puzzles=pool)
    assert len(first) == 5
    assert all(item.theme == "missed_tactic" for item in first)
    assert all(abs(item.rating - 1450) <= 100 for item in first)
    second = select_puzzles("missed_tactic", 1450, 5, exclude_ids={p.id for p in first}, puzzles=pool)
    assert not {p.id for p in first} & {p.id for p in second}
    mixed = select_puzzles("time_pressure", 1450, 5, puzzles=pool)
    assert len({item.theme for item in mixed}) == 5


def test_session_tops_up_with_puzzles_when_player_has_no_games():
    init_db()
    with session_scope() as session:
        player = _player(session)
        plan = build_training_session(session, player.platform, player.username, position_count=5)
        view = training_session_view(session, plan.id)
        assert view is not None
        assert len(view.positions) == 5
        assert all(item.source == "puzzle" and item.rating for item in view.positions)
        first_ids = {
            row.puzzle_id
            for row in session.query(TrainingPositionRow).filter_by(plan_id=plan.id)
        }
        again = build_training_session(session, player.platform, player.username, position_count=5)
        again_ids = {
            row.puzzle_id
            for row in session.query(TrainingPositionRow).filter_by(plan_id=again.id)
        }
        assert len(again_ids) == 5 and not first_ids & again_ids


def test_own_game_positions_come_first_then_puzzles():
    init_db()
    with session_scope() as session:
        player = _player(session, "own-first")
        game = GameRow(
            player_id=player.id,
            external_game_id=uuid.uuid4().hex,
            white=player.username,
            black="opponent",
            result="0-1",
            player_result="loss",
            player_color="white",
        )
        session.add(game)
        session.flush()
        fen = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3"
        session.add(
            CriticalMomentRow(
                game_id=game.id,
                external_moment_id="m1",
                move_number=3,
                ply=5,
                phase="opening",
                theme="king_safety",
                played_san="h3",
                best_san="Bb5",
                fen_before=fen,
                fen_after=fen,
                severity=1.0,
                explanation={"trainable": True, "what_happened": "Slow move."},
            )
        )
        session.flush()
        plan = build_training_session(session, player.platform, player.username, position_count=3)
        view = training_session_view(session, plan.id)
        assert [item.source for item in view.positions] == ["game", "puzzle", "puzzle"]
        assert view.positions[0].fen == fen and view.positions[0].rating is None
        assert all(item.theme == "king_safety" for item in view.positions)

        puzzles_only = build_training_session(
            session, player.platform, player.username, position_count=4, mode="puzzles"
        )
        view = training_session_view(session, puzzles_only.id)
        assert len(view.positions) == 4
        assert {item.source for item in view.positions} == {"puzzle"}
        assert {item.theme for item in view.positions} == {"king_safety"}


def test_puzzle_attempt_is_graded_against_the_solution():
    init_db()
    puzzle = _load_script().convert_row(LICHESS_ROW)
    with session_scope() as session:
        player = _player(session, "grade")
        plan = build_training_session(session, player.platform, player.username, position_count=1)
        row = session.query(TrainingPositionRow).filter_by(plan_id=plan.id).one()
        # Swap in the known Lichess puzzle so the expected answer is fixed.
        row.fen = puzzle["fen"]
        row.correct_move = puzzle["solution_san"]
        row.solution = puzzle["solution"]
        session.flush()

        right = evaluate_attempt(session, row.id, "Rxe7")
        assert right.legal and right.correct and right.best_move == "Rxe7"
        if engine.stockfish_path():
            # Stockfish agrees the Lichess solution keeps the evaluation.
            assert right.cp_loss is not None and right.cp_loss <= 0.5

        wrong = evaluate_attempt(session, row.id, "Qxh7+")
        assert wrong.legal and not wrong.correct
        assert "Rxe7" in wrong.explanation

        illegal = evaluate_attempt(session, row.id, "Ke2")
        assert not illegal.legal and not illegal.correct


def test_training_api_reports_puzzle_source_and_rating(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    username = f"api-puzzles-{uuid.uuid4().hex[:8]}"
    with TestClient(app) as client:
        response = client.post(
            "/api/training/sessions",
            json={
                "platform": "chess.com",
                "username": username,
                "theme": "endgame_conversion",
                "position_count": 3,
                "mode": "puzzles",
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert len(payload["positions"]) == 3
        for position in payload["positions"]:
            assert position["source"] == "puzzle"
            assert isinstance(position["rating"], int)
            assert position["theme"] == "endgame_conversion"
