from datetime import UTC, datetime, timedelta

import chess
import chess.engine
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from chess_coach_agent.api import app
from chess_coach_agent.db import session_scope
from chess_coach_agent.db_models import (
    CriticalMomentRow,
    GameRow,
    PlayerMemoryRow,
    QuizAttemptRow,
    ReviewScheduleRow,
    TrainingPositionRow,
)
from chess_coach_agent.endgames import (
    STRIKES_TO_FAIL,
    Drill,
    get_essential,
    load_essentials,
    own_game_drills,
    play_turn,
    thrown_goal,
)
from chess_coach_agent.engine import LineScore, PositionEval
from chess_coach_agent.engine_api import engine_binary
from chess_coach_agent.repositories import get_or_create_player

client = TestClient(app)
needs_engine = pytest.mark.skipif(engine_binary() is None, reason="Stockfish is not installed")


class ScriptedEngine:
    """Returns the given White-view scores in order and always plays the first legal move."""

    def __init__(self, *scores: int) -> None:
        self.scores = list(scores)

    def evaluate(self, board: chess.Board, multipv: int = 2) -> PositionEval:
        value = self.scores.pop(0)
        return PositionEval(lines=(LineScore(move=next(iter(board.legal_moves)), value=value, cp=value),))


def drill(fen: str, goal: str = "win", finish: str = "engine", move_limit: int = 30) -> Drill:
    return Drill(
        id="test",
        kind="essential",
        title="Test",
        category="Test",
        fen=fen,
        goal=goal,  # type: ignore[arg-type]
        finish=finish,  # type: ignore[arg-type]
        move_limit=move_limit,
        summary="",
        hint="",
    )


# --- essentials data --------------------------------------------------------------------------


def test_essentials_are_legal_positions():
    drills = load_essentials()
    assert 8 <= len(drills) <= 14
    assert len({item.id for item in drills}) == len(drills)
    assert {"King and pawn", "Rook endgames", "Basic mates"} <= {item.category for item in drills}
    for item in drills:
        board = chess.Board(item.fen)
        assert board.is_valid(), item.id
        assert not board.is_game_over(claim_draw=True), item.id
        assert board.fen() == item.fen, f"{item.id}: FEN is not canonical"
        assert item.goal in ("win", "draw") and item.finish in ("engine", "mate"), item.id
        assert item.finish == "engine" or item.goal == "win", item.id
        assert item.move_limit > 0 and item.summary and item.hint, item.id
        assert len(item.id) <= 40


def test_named_positions_have_the_right_material():
    lucena = chess.Board(get_essential("lucena").fen)
    assert lucena.pieces(chess.ROOK, chess.WHITE) and lucena.pieces(chess.ROOK, chess.BLACK)
    assert chess.square_rank(next(iter(lucena.pieces(chess.PAWN, chess.WHITE)))) == 6
    philidor = chess.Board(get_essential("philidor").fen)
    assert philidor.turn == chess.BLACK and len(philidor.pieces(chess.PAWN, chess.WHITE)) == 1
    assert chess.Board(get_essential("queen-mate").fen).pieces(chess.QUEEN, chess.WHITE)


@needs_engine
def test_engine_agrees_with_each_goal():
    engine = chess.engine.SimpleEngine.popen_uci(engine_binary())
    try:
        for item in load_essentials():
            board = chess.Board(item.fen)
            info = engine.analyse(board, chess.engine.Limit(depth=24, time=2))
            score = info["score"].pov(board.turn).score(mate_score=100_000)
            if item.goal == "win":
                assert score >= 300, f"{item.id}: {score}"
            else:
                assert abs(score) <= 50, f"{item.id}: {score}"
    finally:
        engine.quit()


# --- judging ----------------------------------------------------------------------------------


KRK = "8/8/8/3k4/8/8/8/R3K3 w - - 0 1"


def test_engine_replies_while_playing():
    turn = play_turn(drill(KRK), ["a1a4"], 0, ScriptedEngine(900))
    assert turn.status == "playing"
    assert chess.Move.from_uci(turn.reply_uci) in chess.Board("8/8/8/3k4/R7/8/8/4K3 b - - 1 1").legal_moves
    assert turn.fen.split(" ")[1] == "w"


def test_illegal_line_is_rejected():
    with pytest.raises(ValueError):
        play_turn(drill(KRK), ["a1b3"], 0, ScriptedEngine())
    with pytest.raises(ValueError):
        play_turn(drill(KRK), ["a1a4", "d5d4"], 0, ScriptedEngine())


def test_checkmate_passes_without_asking_the_engine():
    item = drill("7k/8/6KQ/8/8/8/8/8 w - - 0 1", finish="mate")
    turn = play_turn(item, ["h6g7"], 0, ScriptedEngine())
    assert (turn.status, turn.result) == ("passed", "converted")


def test_stalemate_fails_a_win_and_passes_a_hold():
    fen = "7k/8/6K1/8/8/8/8/6Q1 w - - 0 1"
    assert play_turn(drill(fen), ["g1g2"], 0, ScriptedEngine(2000)).status == "playing"
    stalemate = "k7/8/2K5/8/8/8/8/1Q6 w - - 0 1"
    item = drill(stalemate)
    turn = play_turn(item, ["b1b6"], 0, ScriptedEngine())
    assert (turn.status, turn.result) == ("failed", "lost_win")
    holder = drill(stalemate, goal="draw")
    assert play_turn(holder, ["b1b6"], 0, ScriptedEngine()).result == "held"


def test_win_slipping_needs_two_turns_in_a_row():
    item = drill(KRK)
    first = play_turn(item, ["a1a4"], 0, ScriptedEngine(20))
    assert first.status == "playing" and first.strikes == 1
    recovered = play_turn(item, ["a1a4"], 1, ScriptedEngine(500))
    assert recovered.strikes == 0
    gone = play_turn(item, ["a1a4"], STRIKES_TO_FAIL - 1, ScriptedEngine(20))
    assert (gone.status, gone.result) == ("failed", "lost_win")


def test_hold_fails_only_when_the_engine_sees_it_lost():
    fen = get_essential("philidor").fen  # the player has Black, so scores flip
    item = drill(fen, goal="draw")
    assert play_turn(item, ["h6c6"], 0, ScriptedEngine(100)).strikes == 0
    assert play_turn(item, ["h6c6"], 0, ScriptedEngine(900)).strikes == 1
    assert play_turn(item, ["h6c6"], 1, ScriptedEngine(900)).result == "lost_draw"


def test_conversion_needs_new_material_not_just_a_big_eval():
    lucena = get_essential("lucena")
    assert play_turn(lucena, ["c1c4"], 0, ScriptedEngine(2000)).status == "playing"
    # Queen against rook is only +400, so a big eval alone does not finish the drill.
    queen_v_rook = drill("3k4/1P6/8/8/8/8/r7/1K6 w - - 0 1")
    assert play_turn(queen_v_rook, ["b7b8q"], 0, ScriptedEngine(2000)).status == "playing"
    rooks_and_pawn = drill("8/1P3k2/8/8/8/r7/7R/7K w - - 0 1")
    assert play_turn(rooks_and_pawn, ["b7b8q"], 0, ScriptedEngine(2000)).result == "converted"


def test_mate_drills_never_adjudicate_a_conversion():
    item = drill("3k4/1P6/8/8/8/8/r7/1K6 w - - 0 1", finish="mate")
    assert play_turn(item, ["b7b8q"], 0, ScriptedEngine(2000)).status != "passed"
    limited = drill(KRK, finish="mate", move_limit=1)
    assert play_turn(limited, ["a1a4"], 0, ScriptedEngine(5000)).status == "failed"


def test_move_limit_is_adjudicated_by_the_engine():
    assert play_turn(drill(KRK, move_limit=1), ["a1a4"], 0, ScriptedEngine(500)).result == "converted"
    assert play_turn(drill(KRK, move_limit=1), ["a1a4"], 0, ScriptedEngine(100)).status == "failed"
    hold = drill(get_essential("philidor").fen, goal="draw", move_limit=1)
    assert play_turn(hold, ["h6c6"], 0, ScriptedEngine(0)).result == "held"


# --- own games --------------------------------------------------------------------------------


def _moves(*scores: tuple[int, int | None]) -> list[dict]:
    return [{"ply": ply, "color": "white" if ply % 2 else "black", "eval_cp": cp} for ply, cp in scores]


def test_thrown_goal():
    moves = _moves((40, 450), (41, 30))
    assert thrown_goal(moves, 41, True, "loss") == "win"
    assert thrown_goal(moves, 41, True, "draw") == "win"
    assert thrown_goal(moves, 41, True, "win") is None  # won anyway
    assert thrown_goal(moves, 41, False, "loss") is None  # Black was losing, nothing to throw
    drawn = _moves((40, 0), (41, -300))
    assert thrown_goal(drawn, 41, True, "loss") == "draw"
    assert thrown_goal(drawn, 41, True, "draw") is None  # the draw was kept after all
    assert thrown_goal(_moves((40, None), (41, 30)), 41, True, "loss") is None  # no engine data
    assert thrown_goal(_moves((40, 450), (41, 400)), 41, True, "loss") is None  # move was fine


def test_thrown_goal_reads_mate_scores():
    moves = [
        {"ply": 40, "color": "black", "eval_mate": 5},
        {"ply": 41, "color": "white", "eval_cp": 10},
    ]
    assert thrown_goal(moves, 41, True, "draw") == "win"


GAME_FEN = "8/8/4k3/8/3K4/4P3/8/8 w - - 0 50"
THROWN_MOVES = [
    {"ply": 98, "color": "black", "eval_cp": 500},
    {"ply": 99, "color": "white", "eval_cp": 0},
]


def _store_game(name: str, external_id: str, result: str = "loss") -> str:
    with session_scope() as session:
        player = get_or_create_player(session, "lichess", name)
        game = GameRow(
            player_id=player.id,
            external_game_id=external_id,
            white=name,
            black="rival",
            result="0-1",
            player_result=result,
            player_color="white",
            played_at="2026.10.01",
            metadata_json={"game": {}, "moves": THROWN_MOVES},
        )
        session.add(game)
        session.flush()
        for ply, phase in ((99, "endgame"), (97, "middlegame")):
            session.add(
                CriticalMomentRow(
                    game_id=game.id,
                    external_moment_id=f"{external_id}-{ply}",
                    move_number=50,
                    ply=ply,
                    phase=phase,
                    theme="endgame_conversion",
                    played_san="Kc4",
                    best_san="Ke5",
                    fen_before=GAME_FEN,
                    fen_after=GAME_FEN,
                    explanation={"better_plan": "Keep the king active."},
                )
            )
        return player.id


def test_own_game_drills_are_found_from_stored_evals():
    _store_game("eg-finder", "eg-game-1")
    _store_game("eg-winner", "eg-game-2", result="win")
    with session_scope() as session:
        found = own_game_drills(session, get_or_create_player(session, "lichess", "eg-finder"))
        none = own_game_drills(session, get_or_create_player(session, "lichess", "eg-winner"))
    assert none == []
    assert [item.id for item in found] == ["game:eg-game-1:99"]
    item = found[0]
    assert (item.goal, item.fen, item.opponent, item.kind) == ("win", GAME_FEN, "rival", "game")
    assert "Kc4" in item.summary and "Ke5" in item.hint


# --- API and scheduling -----------------------------------------------------------------------


def test_list_essentials_without_a_player():
    drills = client.get("/api/endgames").json()["drills"]
    assert {item["kind"] for item in drills} == {"essential"}
    assert all(item["attempts"] == 0 and not item["due"] for item in drills)


def test_unknown_drill_is_404():
    assert client.post("/api/endgames/turn", json={"drill_id": "nope", "moves_uci": ["a1a2"]}).status_code == 404
    response = client.post(
        "/api/endgames/turn",
        json={"drill_id": "game:missing:9", "platform": "lichess", "username": "nobody-here", "moves_uci": ["a1a2"]},
    )
    assert response.status_code == 404


def test_anonymous_result_is_not_recorded():
    response = client.post("/api/endgames/turn", json={"drill_id": "lucena", "resign": True})
    assert response.status_code == 200
    assert response.json()["status"] == "failed" and response.json()["recorded"] is False


def test_results_feed_the_review_schedule():
    request = {"drill_id": "rook-mate", "platform": "lichess", "username": "eg-sched", "resign": True}
    body = client.post("/api/endgames/turn", json=request).json()
    assert body["recorded"] is True and body["interval_days"] == 1
    second = client.post("/api/endgames/turn", json=request).json()
    assert second["interval_days"] == 1

    with session_scope() as session:
        player = get_or_create_player(session, "lichess", "eg-sched")
        rows = session.scalars(select(TrainingPositionRow).where(TrainingPositionRow.source == "essential")).all()
        position = next(row for row in rows if row.fen == get_essential("rook-mate").fen)
        attempts = session.scalars(select(QuizAttemptRow).where(QuizAttemptRow.player_id == player.id)).all()
        schedule = session.scalar(select(ReviewScheduleRow).where(ReviewScheduleRow.position_id == position.id))
        assert len(attempts) == 2 and attempts[0].submitted_move == "resigned"
        assert schedule.player_id == player.id
        schedule.due_at = datetime.now(UTC) - timedelta(hours=1)
        session.flush()

    listed = client.get("/api/endgames", params={"platform": "lichess", "username": "eg-sched"}).json()["drills"]
    item = next(entry for entry in listed if entry["id"] == "rook-mate")
    assert (item["attempts"], item["passes"], item["last_passed"], item["due"]) == (2, 0, False, True)

    # The due drill counts everywhere the existing schedule is read.
    assert client.get("/api/progress/lichess/eg-sched").json()["player"]["due_positions"] == 1
    assert client.get("/api/today/lichess/eg-sched").json()["due"]["count"] == 1
    # Essentials do not count as transfer from the player's games.
    assert client.get("/api/progress/lichess/eg-sched").json()["quiz_accuracy"] == {}


def test_own_game_results_count_toward_theme_accuracy():
    player_id = _store_game("eg-accuracy", "eg-game-3")
    request = {"drill_id": "game:eg-game-3:99", "platform": "lichess", "username": "eg-accuracy", "resign": True}
    assert client.post("/api/endgames/turn", json=request).json()["recorded"] is True
    with session_scope() as session:
        memory = session.get(PlayerMemoryRow, player_id)
        assert memory.quiz_accuracy == {"endgame_conversion": 0.0}


@needs_engine
def test_real_turn_gets_a_stockfish_reply():
    response = client.post(
        "/api/endgames/turn",
        json={"drill_id": "queen-mate", "moves_uci": ["a1a5"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "playing"
    board = chess.Board(get_essential("queen-mate").fen)
    board.push_uci("a1a5")
    board.push_uci(body["reply_uci"])
    assert board.fen() == body["fen"]
    assert body["reply_san"]


@needs_engine
def test_real_engine_fails_a_blundered_hold():
    # Kf6 throws away the opposition; White walks in and the eval goes.
    item = get_essential("opposition-hold")
    board = chess.Board(item.fen)
    moves = ["e6f6"]
    strikes = 0
    response = client.post("/api/endgames/turn", json={"drill_id": item.id, "moves_uci": moves, "strikes": strikes})
    body = response.json()
    assert body["strikes"] == 1 and body["status"] == "playing"
    board.push_uci("e6f6")
    board.push_uci(body["reply_uci"])
    moves.append(body["reply_uci"])
    moves.append(next(iter(board.legal_moves)).uci())
    final = client.post("/api/endgames/turn", json={"drill_id": item.id, "moves_uci": moves, "strikes": 1}).json()
    assert (final["status"], final["result"]) == ("failed", "lost_draw")
