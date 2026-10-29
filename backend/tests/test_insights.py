from __future__ import annotations

import chess
from fastapi.testclient import TestClient

from chess_coach_agent.api import app
from chess_coach_agent.db import session_scope
from chess_coach_agent.db_models import CriticalMomentRow, GameRow
from chess_coach_agent.insights import phase_from_fen, time_category
from chess_coach_agent.pgn import phase_for_board
from chess_coach_agent.repositories import get_or_create_player

LINE = ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5", "c3", "Nf6", "d4", "exd4", "cxd4", "Bb4+"]


def _moves(win_pcts: list[float] | None, clocks: bool = False) -> list[dict]:
    board = chess.Board()
    moves = []
    for index, san in enumerate(LINE):
        fen_before = board.fen()
        color = "white" if board.turn == chess.WHITE else "black"
        move = board.push_san(san)
        record = {
            "ply": index + 1,
            "move_number": index // 2 + 1,
            "color": color,
            "san": san,
            "uci": move.uci(),
            "fen_before": fen_before,
            "fen_after": board.fen(),
        }
        if win_pcts is not None:
            record.update(win_pct=win_pcts[index], accuracy=90.0, win_pct_loss=1.0)
        if clocks:
            record.update(
                clock_seconds=300.0 - index * 10,
                time_spent_seconds=5.0 if index != 4 else 40.0,
                time_pressure=index >= 10,
            )
        moves.append(record)
    return moves


def _seed(username: str, games: list[dict]) -> None:
    with session_scope() as session:
        player = get_or_create_player(session, "chess.com", username)
        for number, spec in enumerate(games):
            row = GameRow(
                player_id=player.id,
                external_game_id=f"{username}-{number}",
                white=username if spec["color"] == "white" else "opp",
                black=username if spec["color"] == "black" else "opp",
                result="*",
                player_result=spec["result"],
                player_color=spec["color"],
                player_elo=1500,
                played_at=f"2026.01.{number + 1:02d}",
                time_control=spec.get("tc", "600"),
                metadata_json={
                    "game": {
                        "player_color": spec["color"],
                        "opponent_elo": spec.get("opp_elo"),
                        **({"termination": spec["termination"]} if "termination" in spec else {}),
                    },
                    "moves": _moves(spec.get("win"), spec.get("clocks", False)),
                },
            )
            session.add(row)
            session.flush()
            for ply, severity in spec.get("moments", []):
                session.add(
                    CriticalMomentRow(
                        game_id=row.id,
                        external_moment_id=f"{row.external_game_id}-{ply}",
                        move_number=(ply + 1) // 2,
                        ply=ply,
                        phase="opening",
                        theme="loose_piece" if severity >= 15 else "missed_tactic",
                        played_san="x",
                        fen_before="",
                        fen_after="",
                        severity=severity,
                    )
                )


# White's Win% after each ply: the player (white) is winning from ply 5 on.
WINNING_WHITE = [55, 50, 60, 55, 80, 78, 82, 80, 85, 84, 86, 85]
LOSING_WHITE = [50, 50, 40, 40, 20, 22, 18, 20, 15, 16, 14, 15]


def test_insights_sections_and_leaks():
    games = []
    for index in range(12):
        games.append(
            {
                "color": "white",
                "result": "draw" if index < 4 else "win",
                "win": WINNING_WHITE,
                "clocks": True,
                "opp_elo": 1800 if index % 2 else 1510,
                "moments": [(5, 20.0)] if index < 4 else [],
                "tc": "180",
            }
        )
    for index in range(12):
        games.append(
            {
                "color": "white",
                "result": "draw" if index < 3 else "loss",
                "win": LOSING_WHITE,
                "moments": [(3, 8.0), (5, 30.0)],
                "termination": "opp won on time" if index == 5 else "opp won by resignation",
            }
        )
    # An older game without engine fields: counts for results and moments only.
    games.append({"color": "black", "result": "loss", "moments": [(4, 16.0)]})
    _seed("insightsplayer", games)

    with TestClient(app) as client:
        response = client.get("/api/insights/chess.com/insightsplayer?last=100")
        assert response.status_code == 200
        data = response.json()

    assert data["games_considered"] == 25
    assert data["engine_games"] == 24
    assert data["clock_games"] == 12

    colors = {row["color"]: row for row in data["colors"]["rows"]}
    assert colors["white"]["games"] == 24 and colors["black"]["games"] == 1
    assert colors["white"]["wins"] == 8 and colors["white"]["draws"] == 7
    assert colors["black"]["accuracy"] is None
    assert data["colors"]["accuracy_sample_size"] == 24

    conversion = data["conversion"]
    assert conversion["sample_size"] == 24
    assert conversion["winning_games"] == 12
    assert conversion["failed_conversions"] == 4
    assert conversion["losing_games"] == 12
    assert conversion["saves"] == 3

    phases = {row["phase"]: row for row in data["phases"]["rows"]}
    assert phases["opening"]["games"] == 25
    # 4 + 12 + 1 blunders (>= 15), 12 inaccuracies, all in the opening.
    assert phases["opening"]["blunder_share_pct"] == 100.0
    assert phases["opening"]["blunders_per_game"] == round(17 / 25, 2)
    assert phases["opening"]["inaccuracies_per_game"] == round(12 / 25, 2)
    assert phases["opening"]["accuracy"] == 90.0

    time = data["time"]
    controls = {row["category"]: row for row in time["by_control"]}
    assert controls["blitz"]["games"] == 12 and controls["rapid"]["games"] == 13
    pressure = {row["state"]: row for row in time["pressure"]}
    assert pressure["time_pressure"]["moves"] == 12  # white plies 11 for 12 games
    assert pressure["normal"]["moves"] == 60
    assert time["time_spent"]["avg_seconds_critical"] == 40.0
    assert time["lost_on_time"] == {
        "sample_size": 12,
        "losses": 9,
        "lost_on_time": 1,
        "pct_of_losses": 11.1,
    }

    opponents = {row["bucket"]: row for row in data["opponents"]["rows"]}
    assert data["opponents"]["sample_size"] == 12
    assert opponents["even"]["games"] == 6 and opponents["much_higher"]["games"] == 6

    leaks = data["leaks"]
    assert 1 <= len(leaks) <= 3
    points = [leak["points_per_10_games"] for leak in leaks]
    assert points == sorted(points, reverse=True)
    top = leaks[0]
    # Every non-won game's dropped points go to loose_piece blunders.
    assert top["action"] == {
        "type": "practice",
        "theme": "loose_piece",
        "label": "Practice these positions",
    }
    ids = {leak["id"] for leak in leaks}
    assert "opening" not in ids  # nobody was -3 by move 12 in these 12-ply games
    assert "conversion" in ids


def test_insights_unknown_player_and_small_samples():
    with TestClient(app) as client:
        empty = client.get("/api/insights/chess.com/nobody-here").json()
        assert empty["games_considered"] == 0 and empty["leaks"] == []
        assert client.get("/api/insights/chess.com/nobody-here?last=5000").status_code == 422

    _seed("fewgames", [{"color": "white", "result": "loss", "moments": [(5, 30.0)]}])
    with TestClient(app) as client:
        data = client.get("/api/insights/chess.com/fewgames").json()
    assert data["games_considered"] == 1
    assert data["leaks"] == []  # below the 10-game minimum


def test_phase_from_fen_matches_board_phase():
    fens = [
        chess.STARTING_FEN,
        "r1bq1rk1/pppp1ppp/2n2n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 0 13",
        "8/5pk1/6p1/8/3R4/6P1/5PK1/8 w - - 0 40",
        "r4rk1/ppp2ppp/2n5/8/8/2N5/PPP2PPP/R4RK1 w - - 0 20",
    ]
    for fen in fens:
        assert phase_from_fen(fen) == phase_for_board(chess.Board(fen))


def test_time_category():
    assert time_category("60") == "bullet"
    assert time_category("180+2") == "blitz"
    assert time_category("300") == "blitz"
    assert time_category("600") == "rapid"
    assert time_category("1/86400") == "daily"
    assert time_category("") is None
