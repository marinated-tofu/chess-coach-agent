import json

import chess
import pytest
from fastapi.testclient import TestClient
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from chess_coach_agent import vision
from chess_coach_agent.api import app
from chess_coach_agent.vision import BoardReading, build_result, position_problems, read_board_image

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
START_ROWS = ["rnbqkbnr", "pppppppp", "8", "8", "8", "8", "PPPPPPPP", "RNBQKBNR"]

client = TestClient(app)


def scripted_model(*readings: dict) -> tuple[FunctionModel, list[int]]:
    """A FunctionModel that returns the given readings in order and counts calls."""
    calls: list[int] = []

    def respond(messages, info: AgentInfo) -> ModelResponse:
        calls.append(len(messages))
        reading = readings[min(len(calls), len(readings)) - 1]
        tool = info.output_tools[0].name
        return ModelResponse(parts=[ToolCallPart(tool, json.dumps(reading))])

    return FunctionModel(respond), calls


def reading(rows, orientation="white_at_bottom", side="unknown", confidence=0.9):
    return {"rows": rows, "orientation": orientation, "side_to_move": side, "confidence": confidence}


def test_start_position_reads_directly():
    board, turn, problems, _ = build_result(BoardReading(**reading(START_ROWS)))
    assert problems == []
    assert board.board_fen() == chess.Board().board_fen()
    assert turn == chess.WHITE


def test_black_at_bottom_is_flipped():
    flipped = ["RNBKQBNR", "PPPPPPPP", "........", "........", "........", "........", "pppppppp", "rnbkqbnr"]
    board, _, problems, orientation = build_result(BoardReading(**reading(flipped, "black_at_bottom")))
    assert problems == []
    assert board.board_fen() == chess.Board().board_fen()


def test_validation_catches_missing_king_and_back_rank_pawn():
    board = chess.Board("4k3/8/8/8/8/8/8/P7 w - - 0 1")
    problems = position_problems(board, chess.WHITE)
    assert any("White has 0 kings" in p for p in problems)
    assert any("a1" in p for p in problems)


def test_side_to_move_inferred_from_check():
    # Black king in check by the rook: it must be Black to move.
    rows = ["4k3", "8", "8", "8", "8", "8", "8", "K3R3"]
    _, turn, problems, _ = build_result(BoardReading(**reading(rows)))
    assert problems == []
    assert turn == chess.BLACK


@pytest.mark.asyncio
async def test_retry_with_feedback_fixes_reading():
    bad = reading(["rnbqqbnr"] + START_ROWS[1:])  # no black king
    model, calls = scripted_model(bad, reading(START_ROWS))
    result = await read_board_image(PNG, "image/png", model=model)
    assert len(calls) == 2
    assert result.valid
    assert result.attempts == 2
    assert result.fen == "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


@pytest.mark.asyncio
async def test_invalid_after_retry_returns_best_guess_with_warnings():
    bad = reading(["rnbqqbnr"] + START_ROWS[1:])
    model, calls = scripted_model(bad, bad)
    result = await read_board_image(PNG, "image/png", model=model)
    assert len(calls) == 2
    assert not result.valid
    assert any("kings" in w for w in result.warnings)
    assert result.confidence <= 0.3


@pytest.mark.asyncio
async def test_no_model_raises_unavailable(monkeypatch):
    monkeypatch.setattr(vision, "_openrouter_model", lambda: None)
    with pytest.raises(vision.VisionUnavailable):
        await read_board_image(PNG, "image/png")


def test_endpoint_returns_fen_and_logs(monkeypatch):
    model, _ = scripted_model(reading(START_ROWS, side="white"))
    monkeypatch.setattr(vision, "_openrouter_model", lambda: model)
    response = client.post("/api/vision/fen", files={"image": ("board.png", PNG, "image/png")})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["fen"].startswith("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq")
    assert body["side_to_move_guess"] == "white"
    assert body["board_ascii"].splitlines()[0] == "r n b q k b n r"


def test_endpoint_rejects_non_images_and_missing_key(monkeypatch):
    response = client.post("/api/vision/fen", files={"image": ("notes.txt", b"hello", "text/plain")})
    assert response.status_code == 415
    monkeypatch.setattr(vision, "_openrouter_model", lambda: None)
    response = client.post("/api/vision/fen", files={"image": ("board.png", PNG, "image/png")})
    assert response.status_code == 503


def test_endpoint_rejects_oversized_upload():
    big = PNG + b"\x00" * (5 * 1024 * 1024)
    response = client.post("/api/vision/fen", files={"image": ("big.png", big, "image/png")})
    assert response.status_code == 413
