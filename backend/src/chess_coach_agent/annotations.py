"""Validate the board arrows and highlights the coach returns.

The coach may only draw what python-chess can confirm: squares must exist, and arrows that
claim to be moves ("best", "played", "threat") must be legal in the position on the player's
board, and "idea" arrows must start on an occupied square. Anything else is dropped and counted.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

from .models import BoardArrow, CoachingOutput, SquareHighlight

MAX_ARROWS = 4
MAX_HIGHLIGHTS = 6
MOVE_KINDS = {"best", "played", "threat"}


@dataclass
class ValidatedAnnotations:
    arrows: list[BoardArrow]
    highlights: list[SquareHighlight]
    dropped: int


def _square(name: str) -> str | None:
    name = name.strip().lower()
    try:
        chess.parse_square(name)
    except ValueError:
        return None
    return name


def _board(fen: str | None) -> chess.Board | None:
    if not fen:
        return None
    try:
        return chess.Board(fen)
    except ValueError:
        return None


def _is_legal(board: chess.Board, from_square: str, to_square: str, *, either_side: bool) -> bool:
    start, end = chess.parse_square(from_square), chess.parse_square(to_square)
    if any(move.from_square == start and move.to_square == end for move in board.legal_moves):
        return True
    if not either_side:
        return False
    # A threat is usually the opponent's move, so also check it with the other side to move.
    other = board.copy(stack=False)
    other.turn = not other.turn
    other.ep_square = None
    return any(move.from_square == start and move.to_square == end for move in other.legal_moves)


def arrow_from_san(fen: str | None, san: str | None) -> BoardArrow | None:
    """Turn a SAN move into a "best" arrow when it is legal in the FEN."""
    board = _board(fen)
    if board is None or not san:
        return None
    try:
        move = board.parse_san(san.strip())
    except ValueError:
        return None
    return BoardArrow(
        from_square=chess.square_name(move.from_square),
        to_square=chess.square_name(move.to_square),
        kind="best",
    )


def validate_annotations(
    fen: str | None,
    arrows: list[BoardArrow],
    highlights: list[SquareHighlight],
    recommended_move: str | None = None,
) -> ValidatedAnnotations:
    board = _board(fen)
    dropped = 0
    kept_arrows: list[BoardArrow] = []
    seen: set[tuple[str, str]] = set()

    auto = arrow_from_san(fen, recommended_move)
    candidates = ([auto] if auto else []) + list(arrows)
    for arrow in candidates:
        start, end = _square(arrow.from_square), _square(arrow.to_square)
        valid = start is not None and end is not None and start != end
        if valid and arrow.kind in MOVE_KINDS:
            valid = board is not None and _is_legal(
                board, start, end, either_side=arrow.kind == "threat"
            )
        elif valid and board is not None:
            # An idea arrow need not be legal now, but it must start from a piece.
            valid = board.piece_at(chess.parse_square(start)) is not None
        if not valid:
            dropped += 1
            continue
        if (start, end) in seen:
            continue
        seen.add((start, end))
        kept_arrows.append(BoardArrow(from_square=start, to_square=end, kind=arrow.kind))

    kept_highlights: list[SquareHighlight] = []
    seen_squares: set[str] = set()
    for highlight in highlights:
        square = _square(highlight.square)
        if square is None:
            dropped += 1
            continue
        if square in seen_squares:
            continue
        seen_squares.add(square)
        kept_highlights.append(SquareHighlight(square=square, kind=highlight.kind))

    return ValidatedAnnotations(
        arrows=kept_arrows[:MAX_ARROWS],
        highlights=kept_highlights[:MAX_HIGHLIGHTS],
        dropped=dropped,
    )


def apply_annotations(coaching: CoachingOutput, fen: str | None) -> tuple[CoachingOutput, int]:
    """Return a copy of the coaching output with only verified annotations, plus the drop count."""
    result = validate_annotations(
        fen, coaching.arrows, coaching.highlights, coaching.recommended_move
    )
    updated = coaching.model_copy(
        update={"arrows": result.arrows, "highlights": result.highlights}
    )
    return updated, result.dropped
