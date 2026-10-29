import asyncio

from pydantic_ai.models.test import TestModel

from chess_coach_agent import llm
from chess_coach_agent.annotations import arrow_from_san, validate_annotations
from chess_coach_agent.models import BoardArrow, SquareHighlight

FEN = "r1b1kbnr/ppp2ppp/2nq4/4p3/8/2N2N2/PPPPBPPP/R1BQK2R w KQkq - 0 5"


def _arrow(start, end, kind):
    return BoardArrow(from_square=start, to_square=end, kind=kind)


def test_legal_arrows_kept_and_illegal_dropped():
    result = validate_annotations(
        FEN,
        [
            _arrow("e1", "g1", "best"),  # castling, legal
            _arrow("c3", "d5", "played"),  # legal knight move
            _arrow("d6", "d2", "threat"),  # black queen takes d2, legal for the side not to move
            _arrow("a1", "a8", "best"),  # rook is blocked: illegal
            _arrow("z9", "e4", "idea"),  # not a square
            _arrow("f3", "g5", "idea"),  # idea arrows need a piece on the start square
            _arrow("f1", "b5", "idea"),  # f1 is empty: dropped
        ],
        [
            SquareHighlight(square="F7", kind="weakness"),
            SquareHighlight(square="i9", kind="focus"),
        ],
    )
    pairs = [(a.from_square, a.to_square, a.kind) for a in result.arrows]
    assert pairs == [
        ("e1", "g1", "best"),
        ("c3", "d5", "played"),
        ("d6", "d2", "threat"),
        ("f3", "g5", "idea"),
    ]
    assert [(h.square, h.kind) for h in result.highlights] == [("f7", "weakness")]
    assert result.dropped == 4


def test_move_arrows_dropped_without_a_fen():
    result = validate_annotations(None, [_arrow("e2", "e4", "best"), _arrow("e2", "e4", "idea")], [])
    assert [a.kind for a in result.arrows] == ["idea"]
    assert result.dropped == 1


def test_recommended_move_becomes_best_arrow():
    arrow = arrow_from_san(FEN, "O-O")
    assert arrow is not None and (arrow.from_square, arrow.to_square) == ("e1", "g1")
    assert arrow_from_san(FEN, "Qxd8") is None
    result = validate_annotations(FEN, [_arrow("e1", "g1", "best")], [], "O-O")
    assert len(result.arrows) == 1 and result.dropped == 0


def test_ask_coach_validates_agent_annotations():
    model = TestModel(
        call_tools=[],
        custom_output_args={
            "answer": "Castle and develop.",
            "evidence": ["Stockfish prefers O-O."],
            "recommended_move": "O-O",
            "principle": "King safety first.",
            "drill": "Castle in five games before move 8.",
            "confidence": 0.8,
            "arrows": [
                {"from_square": "a1", "to_square": "a8", "kind": "best"},
                {"from_square": "c3", "to_square": "d5", "kind": "idea"},
            ],
            "highlights": [{"square": "f7", "kind": "weakness"}],
        },
    )
    response = asyncio.run(llm.ask_coach("What now?", None, fen=FEN, model=model))
    assert response.used_llm is True
    assert [(a.from_square, a.to_square, a.kind) for a in response.arrows] == [
        ("e1", "g1", "best"),
        ("c3", "d5", "idea"),
    ]
    assert response.coaching.arrows == response.arrows
    assert [h.square for h in response.highlights] == ["f7"]
    assert response.annotations_dropped == 1
