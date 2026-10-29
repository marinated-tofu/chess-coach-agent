import pytest
from fastapi.testclient import TestClient

from chess_coach_agent.api import app
from chess_coach_agent.openings import classify_sans, label_game, opening_book


def test_book_loads_all_tsvs():
    assert len(opening_book()) > 3000


@pytest.mark.parametrize(
    ("moves", "eco", "name"),
    [
        ("e4 e5 Nf3 Nc6 Bb5", "C60", "Ruy Lopez"),
        ("e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6", "B90", "Sicilian Defense: Najdorf Variation"),
        ("d4 d5 c4", "D06", "Queen's Gambit"),
        ("e4 e5 Nf3 Nc6 Bc4", "C50", "Italian Game"),
        ("e4 c6", "B10", "Caro-Kann Defense"),
    ],
)
def test_classify_known_lines(moves, eco, name):
    match = classify_sans(moves.split())
    assert match is not None
    assert match.opening.eco == eco
    assert match.opening.name == name


def test_classify_uses_deepest_match_and_survives_leaving_book():
    # Ruy Lopez, then a non-book move: still the Ruy Lopez, book ends at ply 5.
    match = classify_sans("e4 e5 Nf3 Nc6 Bb5 h5 h4".split())
    assert match is not None
    assert match.opening.family == "Ruy Lopez"
    assert match.book_ply == 5


def test_classify_handles_transpositions():
    # 1.Nf3 d5 2.d4 reaches the same position as 1.d4 d5 2.Nf3.
    direct = classify_sans("d4 d5 Nf3".split())
    transposed = classify_sans("Nf3 d5 d4".split())
    assert direct is not None and transposed is not None
    assert direct.opening == transposed.opening


def test_label_game_from_move_dicts():
    import chess

    board = chess.Board()
    moves = []
    for san in "e4 e5 Nf3 Nc6 Bb5".split():
        board.push_san(san)
        moves.append({"fen_after": board.fen()})
    label = label_game(moves)
    assert label == {"eco": "C60", "name": "Ruy Lopez", "family": "Ruy Lopez", "book_ply": 5}
    assert label_game([]) is None


def test_openings_endpoint_with_sample_pgn(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with TestClient(app) as client:
        sample = client.get("/api/sample").json()
        analysis = client.post(
            "/api/analyze",
            json={
                "pgn": sample["pgn"],
                "player": "kfctofu",
                "platform": "pgn",
                "max_games": 1,
            },
        )
        assert analysis.status_code == 200
        game = analysis.json()["analyses"][0]

        response = client.get("/api/openings/pgn/kfctofu")
        assert response.status_code == 200
        payload = response.json()
        assert payload["total_games"] == 1
        assert payload["classified_games"] == 1
        color = game["game"]["player_color"]
        stats = payload[color]
        assert len(stats) == 1
        stat = stats[0]
        assert stat["games"] == 1
        assert stat["wins"] + stat["draws"] + stat["losses"] == 1
        assert 0 <= stat["score_pct"] <= 100
        assert stat["eco"]
        assert stat["name"]

        # Cached second call returns the same body.
        assert client.get("/api/openings/pgn/kfctofu").json() == payload

        label = client.get(
            f"/api/openings/pgn/kfctofu/games/{game['game']['game_id']}"
        )
        assert label.status_code == 200
        assert label.json()["eco"] == stat["eco"]

        variation = client.get("/api/openings/pgn/kfctofu?group=variation").json()
        assert variation[color][0]["name"] == label.json()["name"]

        missing = client.get("/api/openings/pgn/kfctofu/games/nope")
        assert missing.status_code == 404
        empty = client.get("/api/openings/pgn/nobody_here").json()
        assert empty["white"] == [] and empty["black"] == []
