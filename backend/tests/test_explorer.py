import chess
import httpx
import pytest
from fastapi.testclient import TestClient

from chess_coach_agent import explorer
from chess_coach_agent.api import app
from chess_coach_agent.db import session_scope
from chess_coach_agent.db_models import GameRow, PlayerRow
from chess_coach_agent.explorer import GameSummary, build_position_index, query_player_index
from chess_coach_agent.explorer_api import clear_index_cache


def _moves(sans: str, player_color: str, labels: dict[int, str] | None = None) -> list[dict]:
    board = chess.Board()
    out = []
    for ply, san in enumerate(sans.split(), start=1):
        fen_before = board.fen()
        move = board.parse_san(san)
        color = "white" if board.turn else "black"
        uci = move.uci()
        board.push(move)
        out.append(
            {
                "ply": ply,
                "san": san,
                "uci": uci,
                "color": color,
                "fen_before": fen_before,
                "fen_after": board.fen(),
                "is_player_move": color == player_color,
                "accuracy": 80.0 if color == player_color else None,
                "classification": (labels or {}).get(ply),
                "best_san": "Nc3" if (labels or {}).get(ply) else None,
            }
        )
    return out


GAMES = [
    GameSummary("white", "win", "2026.01.01", _moves("e4 e5 Nf3 Nc6", "white")),
    GameSummary("white", "loss", "2026.02.01", _moves("e4 c5 Nf3 d6", "white", {3: "mistake"})),
    GameSummary("white", "draw", "2026.03.01", _moves("e4 c5 Nf3 Nc6", "white", {3: "blunder"})),
    GameSummary("black", "loss", "2026.04.01", _moves("d4 d5 c4", "black")),
]


def test_player_index_counts_from_players_pov():
    index = build_position_index(GAMES)
    start = query_player_index(index, chess.STARTING_FEN, "white")
    assert start["total"] == 3
    (e4,) = start["moves"]
    assert e4["san"] == "e4" and e4["uci"] == "e2e4"
    assert (e4["wins"], e4["draws"], e4["losses"]) == (1, 1, 1)
    assert e4["score_pct"] == 50.0
    assert e4["avg_accuracy"] == 80.0
    assert e4["last_played"] == "2026.03.01"

    both = query_player_index(index, chess.STARTING_FEN, "both")
    assert [m["san"] for m in both["moves"]] == ["e4", "d4"]
    assert both["opening"] is None


def test_player_index_flags_frequent_mistakes():
    index = build_position_index(GAMES)
    after_c5 = _moves("e4 c5", "white")[-1]["fen_after"]
    result = query_player_index(index, after_c5, "white")
    (nf3,) = result["moves"]
    assert nf3["mistakes"] == 2 and nf3["player_moves"] == 2
    assert nf3["frequent_mistake"] is True
    assert result["common_mistake"]["san"] == "Nf3"
    assert result["common_mistake"]["best_san"] == "Nc3"
    assert result["opening"]["name"].startswith("Sicilian")
    # Opponent moves are listed but never count as the player's mistakes.
    after_e4 = _moves("e4", "white")[-1]["fen_after"]
    replies = query_player_index(index, after_e4, "white")
    assert {m["san"] for m in replies["moves"]} == {"e5", "c5"}
    assert all(m["player_moves"] == 0 for m in replies["moves"])


def test_player_endpoint_reads_stored_games():
    clear_index_cache()
    with session_scope() as session:
        player = PlayerRow(platform="lichess", username="ExplorerTester", username_normalized="explorertester")
        session.add(player)
        session.flush()
        for i, game in enumerate(GAMES):
            session.add(
                GameRow(
                    player_id=player.id,
                    external_game_id=f"explorer-{i}",
                    white="a",
                    black="b",
                    result="*",
                    player_result=game.result,
                    player_color=game.color,
                    played_at=game.played_at,
                    metadata_json={"game": {}, "moves": game.moves},
                )
            )
    with TestClient(app) as client:
        response = client.get(
            "/api/explorer/player",
            params={"platform": "lichess", "username": "explorertester", "color": "both"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 4
        assert payload["moves"][0]["san"] == "e4"
        missing = client.get(
            "/api/explorer/player", params={"platform": "lichess", "username": "nobody"}
        )
        assert missing.json()["moves"] == []
        bad = client.get(
            "/api/explorer/player",
            params={"platform": "lichess", "username": "x", "fen": "not a fen"},
        )
        assert bad.status_code == 422


LICHESS_PAYLOAD = {
    "white": 60,
    "draws": 30,
    "black": 10,
    "opening": {"eco": "B00", "name": "King's Pawn"},
    "moves": [
        {"uci": "c7c5", "san": "c5", "averageRating": 2410, "white": 40, "draws": 20, "black": 10,
         "opening": {"eco": "B20", "name": "Sicilian Defense"}},
        {"uci": "e7e5", "san": "e5", "averageRating": 2400, "white": 20, "draws": 10, "black": 0,
         "opening": None},
    ],
    "topGames": [
        {"uci": "c7c5", "id": "abcd1234", "winner": "white",
         "white": {"name": "Carlsen", "rating": 2850}, "black": {"name": "Caruana", "rating": 2800},
         "year": 2019, "month": "2019-01"},
    ],
}


@pytest.fixture
def fresh_lichess():
    explorer.reset_lichess_state()
    yield
    explorer.reset_lichess_state()


def _mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_lichess_proxy_normalizes_and_caches(fresh_lichess):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=LICHESS_PAYLOAD)

    fen = chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1").fen()
    result = explorer.fetch_lichess(fen, "masters", client=_mock_client(handler))
    assert calls[0].url.path == "/masters"
    assert calls[0].headers["User-Agent"].startswith("chess-coach-agent")
    assert result["total"] == 100
    assert result["moves"][0] == {
        "san": "c5", "uci": "c7c5", "games": 70, "white": 40, "draws": 20, "black": 10,
        "avg_rating": 2410, "white_pct": 57.1, "draw_pct": 28.6, "black_pct": 14.3,
        "opening": {"eco": "B20", "name": "Sicilian Defense"},
    }
    assert result["top_games"][0]["url"] == "https://lichess.org/abcd1234"
    explorer.fetch_lichess(fen, "masters", client=_mock_client(handler))
    assert len(calls) == 1


def test_lichess_rate_limit_backs_off(fresh_lichess):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "30"})

    with pytest.raises(explorer.ExplorerUnavailable):
        explorer.fetch_lichess(chess.STARTING_FEN, "lichess", client=_mock_client(handler))
    with pytest.raises(explorer.ExplorerUnavailable, match="rate limiting"):
        explorer.fetch_lichess(chess.STARTING_FEN, "masters", client=_mock_client(handler))
    assert len(calls) == 1


def test_lichess_endpoint_returns_503_json_when_unreachable(fresh_lichess, monkeypatch):
    def boom(*args, **kwargs):
        raise explorer.ExplorerUnavailable("Could not reach the Lichess explorer.")

    monkeypatch.setattr("chess_coach_agent.explorer_api.fetch_lichess", boom)
    with TestClient(app) as client:
        response = client.get("/api/explorer/lichess", params={"db": "masters"})
    assert response.status_code == 503
    assert response.json() == {"error": "Could not reach the Lichess explorer."}


def test_lichess_auth_error_is_explained(fresh_lichess):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="<html>401</html>")

    with pytest.raises(explorer.ExplorerUnavailable, match="LICHESS_API_TOKEN"):
        explorer.fetch_lichess(chess.STARTING_FEN, "masters", client=_mock_client(handler))
