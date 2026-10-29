import chess
import pytest
from fastapi.testclient import TestClient

from chess_coach_agent.api import app
from chess_coach_agent.engine_api import engine_binary

pytestmark = pytest.mark.skipif(engine_binary() is None, reason="Stockfish is not installed")

client = TestClient(app)


def test_analyze_start_position_returns_legal_lines():
    response = client.post("/api/engine/analyze", json={"fen": chess.STARTING_FEN, "depth": 8})
    assert response.status_code == 200
    payload = response.json()
    assert payload["side_to_move"] == "white"
    assert payload["result"] is None
    assert len(payload["lines"]) == 3
    board = chess.Board()
    for rank, line in enumerate(payload["lines"], start=1):
        assert line["rank"] == rank
        move = chess.Move.from_uci(line["move_uci"])
        assert move in board.legal_moves
        assert board.san(move) == line["move_san"]
        assert line["pv_san"][0] == line["move_san"]
        assert 1 <= len(line["pv_san"]) <= 8
        assert line["eval_cp"] is not None and abs(line["eval_cp"]) < 150


def test_analyze_finds_mate_in_one_from_white_pov():
    # Black to move mates with Qh4# (fool's mate), so the mate is negative from White's view.
    fen = "rnbqkbnr/pppp1ppp/8/4p3/6P1/5P2/PPPPP2P/RNBQKBNR b KQkq - 0 2"
    response = client.post("/api/engine/analyze", json={"fen": fen, "multipv": 1, "depth": 6})
    assert response.status_code == 200
    best = response.json()["lines"][0]
    assert best["move_san"] == "Qh4#"
    assert best["mate"] == -1
    assert best["eval_cp"] is None


def test_analyze_rejects_invalid_fen():
    assert client.post("/api/engine/analyze", json={"fen": "not a fen"}).status_code == 422
    # Parses, but both kings missing is not a legal position.
    assert client.post("/api/engine/analyze", json={"fen": "8/8/8/8/8/8/8/8 w - - 0 1"}).status_code == 422
    assert client.post("/api/engine/move", json={"fen": "nope", "level": 1}).status_code == 422


def test_analyze_checkmate_position_reports_result():
    fen = "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"
    payload = client.post("/api/engine/analyze", json={"fen": fen}).json()
    assert payload["lines"] == []
    assert payload["result"] == "checkmate"
    stalemate = "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"
    assert client.post("/api/engine/analyze", json={"fen": stalemate}).json()["result"] == "stalemate"
    assert client.post("/api/engine/move", json={"fen": fen, "level": 1}).status_code == 422


@pytest.mark.parametrize("level", [1, 5, 8])
def test_bot_returns_legal_move(level):
    fen = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3"
    response = client.post("/api/engine/move", json={"fen": fen, "level": level})
    assert response.status_code == 200
    payload = response.json()
    board = chess.Board(fen)
    move = chess.Move.from_uci(payload["move_uci"])
    assert move in board.legal_moves
    assert board.san(move) == payload["move_san"]
    board.push(move)
    assert payload["fen_after"] == board.fen()


def test_bot_level_out_of_range_is_rejected():
    assert client.post("/api/engine/move", json={"fen": chess.STARTING_FEN, "level": 9}).status_code == 422
