import pytest
from pydantic_ai.models.test import TestModel

from chess_coach_agent.llm import COACH_INSTRUCTIONS, ask_coach, scrub_fen

FEN = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3"


def test_full_fen_becomes_words():
    assert scrub_fen(f"Look at {FEN} and find the plan.") == "Look at this position and find the plan."


def test_fen_aside_is_removed():
    text = f"Set up the position after 2...Nc6 (FEN: {FEN}). Find a developing move."
    assert scrub_fen(text) == "Set up the position after 2...Nc6. Find a developing move."


def test_board_only_fen_in_backticks_and_label():
    board = FEN.split()[0]
    assert scrub_fen(f"Drill: FEN `{board}` — White to move.") == "Drill: this position — White to move."


def test_san_squares_and_ordinary_slashes_survive():
    text = "Play Nf3 and O-O; win/draw/loss is 5/2/3 and the e4/d4 centre holds."
    assert scrub_fen(text) == text


def test_instructions_forbid_fen_and_spoilers():
    assert "Never put a FEN" in COACH_INSTRUCTIONS
    assert "never gives away" in COACH_INSTRUCTIONS


@pytest.mark.asyncio
async def test_ask_coach_strips_fen_from_every_text_field():
    model = TestModel(
        call_tools=[],
        custom_output_args={
            "answer": f"In {FEN} White should castle.",
            "evidence": [f"Engine line from {FEN}: O-O is best."],
            "recommended_move": "O-O",
            "principle": "Castle early.",
            "drill": f"From `{FEN}` find the safest king move without looking at the engine.",
            "confidence": 0.7,
        },
    )
    response = await ask_coach("What now?", None, model=model)
    coaching = response.coaching
    for text in [response.answer, coaching.answer, coaching.principle, coaching.drill, *coaching.evidence]:
        assert "/" not in text, text
    assert coaching.answer == "In this position White should castle."
    assert coaching.recommended_move == "O-O"
