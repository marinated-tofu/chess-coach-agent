"""Read a chess position from a board screenshot or photo with a vision model.

The model only transcribes squares. python-chess builds and checks the position, and a
failed check goes back to the model once as feedback before we fall back to warnings.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from textwrap import dedent
from typing import Any, Literal

import chess
from pydantic import BaseModel, Field
from pydantic_ai import Agent, BinaryContent
from pydantic_ai.models.openai import OpenAIChatModel

from .llm import _openrouter_model

MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_MEDIA_TYPES = ("image/png", "image/jpeg", "image/webp")
PIECE_LETTERS = set("prnbqkPRNBQK")


class BoardReading(BaseModel):
    """What the vision model returns: the board exactly as drawn in the image."""

    top_rank_label: str = Field(
        default="",
        description="The rank number printed beside the image's top row ('8' or '1'), or '' if none.",
    )
    rows: list[str] = Field(
        description=(
            "8 strings, the image's top row first. Each string is 8 space-separated tokens read "
            "left to right: K Q R B N P for white pieces, k q r b n p for black, '.' for empty."
        )
    )
    orientation: Literal["white_at_bottom", "black_at_bottom"] = Field(
        description="Which side's pieces start at the bottom edge of the image."
    )
    side_to_move: Literal["white", "black", "unknown"] = Field(
        default="unknown",
        description="Only if the image shows it (a highlighted last move, a clock, a caption).",
    )
    confidence: float = Field(default=0.5, ge=0, le=1)
    notes: str = Field(default="", description="Squares you were unsure about, briefly.")

    def resolved_orientation(self) -> Literal["white_at_bottom", "black_at_bottom"]:
        label = self.top_rank_label.strip()
        if label == "1":
            return "black_at_bottom"
        if label == "8":
            return "white_at_bottom"
        return self.orientation


class VisionResult(BaseModel):
    fen: str
    side_to_move_guess: Literal["white", "black"]
    confidence: float
    warnings: list[str] = Field(default_factory=list)
    board_ascii: str
    valid: bool
    orientation: Literal["white_at_bottom", "black_at_bottom"]
    attempts: int
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    duration_ms: float = 0


class VisionUnavailable(RuntimeError):
    """No API key configured."""


VISION_INSTRUCTIONS = dedent(
    """
    You transcribe chess diagrams, screenshots and photos into text.
    1. Find the board and its coordinate labels. Report the rank number printed next to the
       top row as top_rank_label ('8' means White is at the bottom, '1' means Black is).
    2. Read the board one row at a time, top row first, each row left to right exactly as it
       appears. Do not rotate or flip anything yourself. Write each row as 8 space-separated
       tokens, one per square: K Q R B N P for white (light) pieces, k q r b n p for black
       (dark) pieces, '.' for an empty square. Count to 8 for every row.
    3. Set orientation from the labels; without labels, use where the kings and pawn chains sit.
    Piece shapes: king = tallest, with a cross; queen = crown of points; bishop = mitre with a
    slit; knight = horse head; rook = tower with battlements; pawn = small round head.
    """
).strip()


# In a six-board check (opening, middlegame, endgame, two flipped boards, a tactic) this model
# read 6/6 boards exactly; the coach default (claude-haiku-5.5) read 3/6. Override with VISION_MODEL.
DEFAULT_VISION_MODEL = "google/gemini-3.8-flash"


def vision_model_name() -> str:
    return os.getenv("VISION_MODEL") or DEFAULT_VISION_MODEL


def estimate_vision_cost(input_tokens: int, output_tokens: int) -> float:
    """USD estimate at the vision model's OpenRouter list price (defaults: gemini-3.8-flash)."""
    input_rate = float(os.getenv("VISION_INPUT_COST_PER_MILLION", "0.83"))
    output_rate = float(os.getenv("VISION_OUTPUT_COST_PER_MILLION", "4.12"))
    return round((input_tokens * input_rate + output_tokens * output_rate) / 1_000_000, 8)


def _vision_model() -> Any:
    """Reuse the coach's OpenRouter provider and settings with the vision model's name."""
    base = _openrouter_model()
    if not isinstance(base, OpenAIChatModel) or vision_model_name() == base.model_name:
        return base
    return OpenAIChatModel(vision_model_name(), provider=base._provider, settings=base.settings)  # type: ignore[attr-defined,arg-type]


@dataclass
class _Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    warnings: list[str] = field(default_factory=list)


def create_vision_agent(model: Any = None) -> Agent[None, BoardReading]:
    return Agent(
        model if model is not None else _vision_model(),
        output_type=BoardReading,
        instructions=VISION_INSTRUCTIONS,
        retries=2,
    )


def _normalize_row(row: str) -> str:
    """Accept '.'-rows, FEN digits, spaces or dashes; return 8 chars or raise ValueError."""
    cells: list[str] = []
    for char in row.strip():
        if char.isdigit():
            cells.extend("." * int(char))
        elif char in PIECE_LETTERS:
            cells.append(char)
        elif char in ".-_0x":
            cells.append(".")
        elif char in " /|":
            continue
        else:
            raise ValueError(f"unknown symbol {char!r} in row {row!r}")
    if len(cells) != 8:
        raise ValueError(f"row {row!r} has {len(cells)} squares instead of 8")
    return "".join(cells)


def board_from_reading(
    reading: BoardReading, orientation: Literal["white_at_bottom", "black_at_bottom"] | None = None
) -> chess.Board:
    """Turn the image-space grid into a board with White's first rank at the bottom."""
    if len(reading.rows) != 8:
        raise ValueError(f"expected 8 rows, got {len(reading.rows)}")
    grid = [_normalize_row(row) for row in reading.rows]
    if (orientation or reading.resolved_orientation()) == "black_at_bottom":
        grid = [row[::-1] for row in reversed(grid)]
    board = chess.Board(None)
    for row_index, row in enumerate(grid):
        rank = 7 - row_index
        for file, char in enumerate(row):
            if char != ".":
                board.set_piece_at(chess.square(file, rank), chess.Piece.from_symbol(char))
    return board


def _castling_fen(board: chess.Board) -> str:
    rights = ""
    for color, back, king_sq, letters in (
        (chess.WHITE, 0, chess.E1, "KQ"),
        (chess.BLACK, 7, chess.E8, "kq"),
    ):
        if board.piece_at(king_sq) != chess.Piece(chess.KING, color):
            continue
        if board.piece_at(chess.square(7, back)) == chess.Piece(chess.ROOK, color):
            rights += letters[0]
        if board.piece_at(chess.square(0, back)) == chess.Piece(chess.ROOK, color):
            rights += letters[1]
    return rights or "-"


def position_problems(board: chess.Board, turn: chess.Color) -> list[str]:
    """Human-readable reasons the position cannot be real (empty list = plausible)."""
    problems: list[str] = []
    for color, name in ((chess.WHITE, "White"), (chess.BLACK, "Black")):
        kings = len(board.pieces(chess.KING, color))
        if kings != 1:
            problems.append(f"{name} has {kings} kings; there must be exactly one.")
        pawns = len(board.pieces(chess.PAWN, color))
        if pawns > 8:
            problems.append(f"{name} has {pawns} pawns; the maximum is 8.")
        total = chess.popcount(board.occupied_co[color])
        if total > 16:
            problems.append(f"{name} has {total} pieces; the maximum is 16.")
        extra = (
            max(0, len(board.pieces(chess.QUEEN, color)) - 1)
            + max(0, len(board.pieces(chess.ROOK, color)) - 2)
            + max(0, len(board.pieces(chess.BISHOP, color)) - 2)
            + max(0, len(board.pieces(chess.KNIGHT, color)) - 2)
        )
        if extra > 8 - pawns:
            problems.append(f"{name} has more promoted pieces than missing pawns allow.")
    back_rank_pawns = board.pieces(chess.PAWN, chess.WHITE) | board.pieces(chess.PAWN, chess.BLACK)
    for square in back_rank_pawns:
        if chess.square_rank(square) in (0, 7):
            problems.append(f"There is a pawn on {chess.square_name(square)}; pawns never stand on the 1st or 8th rank.")
    if not problems:
        probe = board.copy()
        probe.turn = not turn
        if probe.is_check():
            side = "White" if turn == chess.BLACK else "Black"
            problems.append(f"{side} is in check but it is not {side}'s move.")
    return problems


def _evaluate(
    reading: BoardReading, orientation: Literal["white_at_bottom", "black_at_bottom"]
) -> tuple[chess.Board, chess.Color, list[str]]:
    board = board_from_reading(reading, orientation)
    turn = chess.BLACK if reading.side_to_move == "black" else chess.WHITE
    problems = position_problems(board, turn)
    if problems and reading.side_to_move == "unknown":
        # Only the side to move may be wrong: try the other one before reporting problems.
        if not position_problems(board, not turn):
            return board, not turn, []
    return board, turn, problems


def build_result(
    reading: BoardReading,
) -> tuple[chess.Board, chess.Color, list[str], Literal["white_at_bottom", "black_at_bottom"]]:
    orientation = reading.resolved_orientation()
    board, turn, problems = _evaluate(reading, orientation)
    if problems and not reading.top_rank_label.strip():
        # No labels to go by: the other orientation may be the one that makes sense.
        other = "black_at_bottom" if orientation == "white_at_bottom" else "white_at_bottom"
        board2, turn2, problems2 = _evaluate(reading, other)
        if len(problems2) < len(problems):
            return board2, turn2, problems2, other
    return board, turn, problems, orientation


def _fen(board: chess.Board, turn: chess.Color) -> str:
    probe = board.copy()
    probe.turn = turn
    probe.set_castling_fen(_castling_fen(board))
    probe.ep_square = None
    probe.halfmove_clock = 0
    probe.fullmove_number = 1
    # Drop castling rights python-chess considers inconsistent.
    probe.castling_rights = probe.clean_castling_rights()
    return probe.fen()


def _record_usage(usage: _Usage, result: Any) -> None:
    run_usage = result.usage
    usage.input_tokens += run_usage.input_tokens or 0
    usage.output_tokens += run_usage.output_tokens or 0


async def read_board_image(
    image: bytes, media_type: str, *, model: Any = None, timeout: float | None = None
) -> VisionResult:
    selected = model if model is not None else _vision_model()
    if selected is None:
        raise VisionUnavailable("OPENROUTER_API_KEY is not configured")
    agent = create_vision_agent(selected)
    limit = timeout if timeout is not None else float(os.getenv("VISION_TIMEOUT_SECONDS", "40"))
    started = time.perf_counter()
    usage = _Usage()

    async def run() -> VisionResult:
        prompt: list[Any] = [
            "Transcribe this chess board.",
            BinaryContent(data=image, media_type=media_type),
        ]
        result = await agent.run(prompt)
        _record_usage(usage, result)
        reading = result.output
        attempts = 1
        orientation = reading.resolved_orientation()
        try:
            board, turn, problems, orientation = build_result(reading)
        except ValueError as exc:
            board, turn, problems = None, chess.WHITE, [str(exc)]

        if problems:
            feedback = (
                "That transcription is not a legal chess position: "
                + " ".join(problems)
                + " Look at the image again square by square and return a corrected transcription."
            )
            retry = await agent.run(feedback, message_history=result.all_messages())
            _record_usage(usage, retry)
            attempts = 2
            try:
                board2, turn2, problems2, orientation2 = build_result(retry.output)
                if board is None or len(problems2) <= len(problems):
                    reading, board, turn, problems = retry.output, board2, turn2, problems2
                    orientation = orientation2
            except ValueError as exc:
                if board is None:
                    problems = [str(exc)]

        if board is None:
            raise ValueError("The model did not return a readable 8x8 board. " + " ".join(problems))
        warnings = list(problems)
        if reading.side_to_move == "unknown":
            warnings.append("Side to move is a guess; set it before analysing.")
        if reading.notes.strip() and (problems or reading.confidence < 0.8):
            warnings.append(f"Unsure: {reading.notes.strip()}")
        confidence = reading.confidence if not problems else min(reading.confidence, 0.3)
        return VisionResult(
            fen=_fen(board, turn),
            side_to_move_guess="white" if turn == chess.WHITE else "black",
            confidence=round(confidence, 2),
            warnings=warnings,
            board_ascii=str(board),
            valid=not problems,
            orientation=orientation,
            attempts=attempts,
        )

    outcome = await asyncio.wait_for(run(), timeout=limit)
    return outcome.model_copy(
        update={
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "model": vision_model_name(),
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    )


def sniff_media_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None
