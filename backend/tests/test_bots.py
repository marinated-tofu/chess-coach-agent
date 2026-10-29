import random

import chess
import chess.engine
import pytest
from fastapi.testclient import TestClient

from chess_coach_agent.api import app
from chess_coach_agent.bots import (
    BOTS_BY_ID,
    BotContext,
    analyse_candidates,
    blunder_chance,
    choose_from_candidates,
    sparring_book,
    temperature,
)
from chess_coach_agent.db import session_scope
from chess_coach_agent.db_models import GameRow, PlayerRow
from chess_coach_agent.engine_api import engine_binary

client = TestClient(app)
needs_engine = pytest.mark.skipif(engine_binary() is None, reason="Stockfish is not installed")

# Middlegame positions with plenty of legal moves and real ways to go wrong.
POSITIONS = [
    "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4",
    "r1bq1rk1/ppp2ppp/2np1n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 0 7",
    "r2qkb1r/pp2pppp/2n2n2/3p1b2/3P4/2N1PN2/PP3PPP/R1BQKB1R w KQkq - 1 6",
    "rnbqk2r/ppp1bppp/4pn2/3p4/2PP4/2N2N2/PP2PPPP/R1BQKB1R w KQkq - 4 5",
    "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/3P1N2/PPP2PPP/RNBQK2R b KQkq - 0 5",
    "2r2rk1/pp1bqppp/2nbpn2/3p4/3P4/2NBPN2/PPQ2PPP/2R2RK1 b - - 5 13",
]


def test_list_bots():
    payload = client.get("/api/bots").json()
    bots = payload["bots"]
    assert 6 <= len(bots) <= 8
    ratings = [bot["rating"] for bot in bots]
    assert min(ratings) <= 600 and max(ratings) >= 2200
    assert {"solid", "aggressive", "tricky", "sparring"} <= {bot["style"] for bot in bots}
    assert all(bot["name"] and bot["initial"] and bot["color"].startswith("#") for bot in bots)


def test_curves_are_calibrated():
    # About 1 blunder in 15 moves at 1200; rare at 2000.
    assert 1 / 18 < blunder_chance(1200) < 1 / 12
    assert blunder_chance(2000) < 0.015
    assert temperature(600) > temperature(1200) > temperature(2000)


@needs_engine
def test_bot_moves_are_legal():
    for bot_id in ("theo", "kit", "lena"):
        for fen in POSITIONS[:3]:
            response = client.post("/api/bots/move", json={"fen": fen, "bot_id": bot_id, "moves_uci": ["x"] * 30})
            assert response.status_code == 200, response.text
            body = response.json()
            board = chess.Board(fen)
            move = chess.Move.from_uci(body["move_uci"])
            assert move in board.legal_moves
            assert board.san(move) == body["move_san"]
            board.push(move)
            assert board.fen() == body["fen_after"]
            assert 0 < body["thinking_ms"] <= 4000


@needs_engine
def test_deterministic_with_seed():
    request = {"fen": POSITIONS[1], "bot_id": "theo", "moves_uci": ["x"] * 30, "seed": 7}
    first = client.post("/api/bots/move", json=request).json()
    for _ in range(3):
        again = client.post("/api/bots/move", json=request).json()
        assert again["move_uci"] == first["move_uci"]
        assert again["thinking_ms"] == first["thinking_ms"]


@needs_engine
def test_low_rated_bot_loses_more_often():
    """Over a fixed position set, the 600 bot picks clearly losing moves far more than the 2200 bot."""
    engine = chess.engine.SimpleEngine.popen_uci(engine_binary())
    try:
        analysed = [(chess.Board(fen), analyse_candidates(engine, chess.Board(fen), 2200)) for fen in POSITIONS]
    finally:
        engine.quit()

    def losing_rate(rating: int) -> float:
        rng = random.Random(1)
        bad = total = 0
        for board, candidates in analysed:
            for _ in range(150):
                decision = choose_from_candidates(board, candidates, rating, "solid", rng)
                total += 1
                # Moves from outside the analysed top 8 count as losing.
                if decision.loss is None or decision.loss >= 5:
                    bad += 1
        return bad / total

    low, high = losing_rate(600), losing_rate(2200)
    print(f"losing-move rate: 600={low:.3f} 2200={high:.3f}")
    assert low > 0.15
    assert high < 0.08
    assert low > 4 * high


def _store_game(username: str, opponent_moves: dict[int, str], player_color: str, index: int) -> None:
    """One stored game where the opponent played the given SAN at the given plies."""
    board = chess.Board()
    moves = []
    sans = ["e4", "c6", "d4", "d5", "Nc3", "dxe4"]
    for ply, san in enumerate(sans, start=1):
        san = opponent_moves.get(ply, san)
        move = board.parse_san(san)
        is_player = (ply % 2 == 1) == (player_color == "white")
        moves.append({"ply": ply, "san": san, "uci": move.uci(), "fen_before": board.fen(), "is_player_move": is_player})
        board.push(move)
    with session_scope() as session:
        player = session.query(PlayerRow).filter_by(platform="lichess", username_normalized=username).one_or_none()
        if player is None:
            player = PlayerRow(platform="lichess", username=username, username_normalized=username, current_rating=1400)
            session.add(player)
            session.flush()
        session.add(
            GameRow(
                player_id=player.id,
                external_game_id=f"{username}-{index}",
                white=username if player_color == "white" else "opp",
                black="opp" if player_color == "white" else username,
                result="1-0",
                player_result="win",
                player_color=player_color,
                metadata_json={"moves": moves},
            )
        )


def test_sparring_uses_opponents_book_move():
    # The player is White; opponents answered 1.e4 with the Caro-Kann 5 times, the Sicilian once.
    for index in range(5):
        _store_game("sparkid", {}, "white", index)
    _store_game("sparkid", {2: "c5", 4: "d6", 6: "cxd4"}, "white", 99)
    book = sparring_book("lichess", "sparkid")
    after_e4 = chess.Board()
    after_e4.push_san("e4")
    assert book[after_e4.epd()]["c7c6"] == 5
    # The player's own moves never go in the book.
    assert chess.Board().epd() not in book

    picks = []
    for seed in range(6):
        response = client.post(
            "/api/bots/move",
            json={
                "fen": after_e4.fen(),
                "bot_id": "sparring",
                "moves_uci": ["e2e4"],
                "platform": "lichess",
                "username": "SparKid",
                "seed": seed,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["source"] == "sparring"
        assert body["rating"] == 1400
        assert "opponents played" in body["comment"]
        picks.append(body["move_san"])
    assert set(picks) <= {"c6", "c5"}
    assert picks.count("c6") >= 3


def test_sparring_context_falls_back_to_tsv_book():
    from chess_coach_agent.bots import choose_move

    context = BotContext(bot=BOTS_BY_ID["sparring"], rating=1500, ply=0, sparring={})
    decision = choose_move(None, chess.Board(), context, random.Random(3))
    assert decision.source == "book"
    assert decision.move in chess.Board().legal_moves


def test_game_over_and_bad_input():
    mate = "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"
    response = client.post("/api/bots/move", json={"fen": mate, "bot_id": "theo"})
    assert response.status_code == 422
    assert "already over (checkmate)" in response.json()["detail"]
    stalemate = "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"
    assert "stalemate" in client.post("/api/bots/move", json={"fen": stalemate, "bot_id": "lena"}).json()["detail"]
    assert client.post("/api/bots/move", json={"fen": "nope", "bot_id": "theo"}).status_code == 422
    assert client.post("/api/bots/move", json={"fen": chess.STARTING_FEN, "bot_id": "nobody"}).status_code == 404
