import io

import chess
import chess.pgn
from fastapi.testclient import TestClient

from chess_coach_agent.api import app
from chess_coach_agent.db import session_scope
from chess_coach_agent.models import (
    AnalyzeResponse,
    CoachAnalysis,
    CriticalMoment,
    GameMetadata,
    MoveRecord,
    SideAccuracy,
)
from chess_coach_agent.pgn_export import build_annotated_pgn, pgn_filename
from chess_coach_agent.repositories import persist_analyses


def _moves(sans: list[str], extra: dict[int, dict] | None = None) -> list[MoveRecord]:
    board = chess.Board()
    records = []
    for index, san in enumerate(sans):
        before = board.fen()
        move = board.parse_san(san)
        board.push(move)
        records.append(
            MoveRecord(
                ply=index + 1,
                move_number=index // 2 + 1,
                color="white" if index % 2 == 0 else "black",
                san=san,
                uci=move.uci(),
                fen_before=before,
                fen_after=board.fen(),
                **(extra or {}).get(index + 1, {}),
            )
        )
    return records


def _analysis(game_id: str = "pgnexport1") -> CoachAnalysis:
    extra = {
        1: {"eval_cp": 30, "classification": "best", "clock_seconds": 299.0},
        2: {"eval_cp": 35, "clock_seconds": 298.5},
        3: {"eval_cp": 40, "classification": "great", "clock_seconds": 290.0},
        4: {
            "eval_cp": 250,
            "classification": "mistake",
            "best_san": "Nc6",
            "best_uci": "b8c6",
            "clock_seconds": 3725.0,
        },
        5: {"eval_mate": 3, "classification": "inaccuracy", "best_san": "Qh5"},
    }
    moves = _moves(["e4", "e5", "Nf3", "f6", "Nxe5"], extra)
    moment = CriticalMoment(
        id="m1",
        game_id=game_id,
        ply=4,
        move_number=2,
        phase="opening",
        theme="weak king",
        played_san="f6",
        best_san="Nc6",
        fen_before=moves[3].fen_before,
        fen_after=moves[3].fen_after,
        judgment="mistake",
        win_probability_loss=20,
        move_accuracy=40,
        summary="f6 weakens the king.",
        what_happened="f6 weakens the e8-h5 diagonal.",
        better_plan="Develop with Nc6 and defend e5.",
        principle="Don't weaken the king.",
        drill_prompt="Find the best move.",
    )
    return CoachAnalysis(
        game=GameMetadata(
            game_id=game_id,
            source="chess.com",
            white="Alice Smith",
            black="bob/\"x\"",
            result="1-0",
            date="2026.01.02",
            link="https://www.chess.com/game/live/1",
            time_control="300",
        ),
        moves=moves,
        moments=[moment],
        summary="",
        training_plan=[],
        accuracy=SideAccuracy(white=91.2, black=55.0),
    )


def _parse(pgn: str) -> chess.pgn.Game:
    game = chess.pgn.read_game(io.StringIO(pgn))
    assert game is not None
    assert not game.errors
    return game


def test_round_trip_nags_evals_clocks_variation():
    pgn = build_annotated_pgn(_analysis())
    game = _parse(pgn)
    assert game.headers["Annotator"] == "Chess Coach Agent"
    assert game.headers["White"] == "Alice Smith"
    assert game.headers.get("ECO")  # Petrov/Damiano family is in the book
    assert "Accuracy" in game.comment and "91.2%" in game.comment

    nodes = list(game.mainline())
    assert [node.san() for node in nodes] == ["e4", "e5", "Nf3", "f6", "Nxe5"]
    assert chess.pgn.NAG_GOOD_MOVE in nodes[2].nags
    assert chess.pgn.NAG_MISTAKE in nodes[3].nags
    assert chess.pgn.NAG_DUBIOUS_MOVE in nodes[4].nags
    assert not nodes[0].nags

    assert nodes[0].eval().white().score() == 30
    assert nodes[3].eval().white().score() == 250
    assert nodes[4].eval().white().mate() == 3
    assert nodes[0].clock() == 299.0
    assert nodes[1].clock() == 298.5
    assert nodes[3].clock() == 3725.0
    assert "[%clk 1:02:05]" in pgn

    assert "Mistake. Nc6 was best." in nodes[3].comment
    assert "Develop with Nc6" in nodes[3].comment
    assert "Inaccuracy. Qh5 was best." in nodes[4].comment

    parent = nodes[3].parent
    assert len(parent.variations) == 2
    assert parent.variations[1].san() == "Nc6"


def test_options_disable_evals_clocks_variations():
    pgn = build_annotated_pgn(
        _analysis(), include_evals=False, include_clocks=False, include_variations=False
    )
    game = _parse(pgn)
    assert "[%eval" not in pgn and "[%clk" not in pgn
    assert all(len(node.variations) <= 1 for node in game.mainline())
    assert chess.pgn.NAG_MISTAKE in list(game.mainline())[3].nags


def test_old_analysis_without_new_fields():
    moves = _moves(["d4", "d5", "c4"])
    analysis = CoachAnalysis(
        game=GameMetadata(game_id="old", white="a", black="b", result="*"),
        moves=moves,
        moments=[],
        summary="",
        training_plan=[],
    )
    game = _parse(build_annotated_pgn(analysis))
    assert [node.san() for node in game.mainline()] == ["d4", "d5", "c4"]
    assert all(node.eval() is None and node.clock() is None for node in game.mainline())
    assert pgn_filename(analysis) == "a-vs-b-undated.pgn"


def test_filename_is_sanitized():
    assert pgn_filename(_analysis()) == "Alice_Smith-vs-bob_x-2026-01-02.pgn"


def test_endpoint_returns_attachment():
    analysis = _analysis("pgnexport-api")
    with session_scope() as session:
        persist_analyses(session, "chess.com", "pgnexporter", AnalyzeResponse(analyses=[analysis]))
    with TestClient(app) as client:
        response = client.get("/api/games/chess.com/pgnexporter/pgnexport-api/pgn")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-chess-pgn")
        assert (
            response.headers["content-disposition"]
            == 'attachment; filename="Alice_Smith-vs-bob_x-2026-01-02.pgn"'
        )
        game = _parse(response.text)
        assert len(list(game.mainline_moves())) == 5

        bare = client.get(
            "/api/games/chess.com/pgnexporter/pgnexport-api/pgn?evals=0&clocks=0&variations=0"
        )
        assert "[%eval" not in bare.text and "[%clk" not in bare.text

        missing = client.get("/api/games/chess.com/pgnexporter/nope/pgn")
        assert missing.status_code == 404
