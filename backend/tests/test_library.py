from datetime import UTC, datetime, timedelta

import chess
from fastapi.testclient import TestClient

from chess_coach_agent import library_api
from chess_coach_agent.api import app
from chess_coach_agent.db import session_scope
from chess_coach_agent.db_models import (
    AnalysisRow,
    CriticalMomentRow,
    GameRow,
    PlayerRow,
    ReviewScheduleRow,
    TrainingPlanRow,
    TrainingPositionRow,
)

PLATFORM = "chess.com"
USERNAME = "librarytester"


def _moves(sans: list[str]) -> list[dict]:
    board = chess.Board()
    moves = []
    for ply, san in enumerate(sans, start=1):
        before = board.fen()
        move = board.push_san(san)
        moves.append(
            {
                "ply": ply,
                "move_number": (ply + 1) // 2,
                "color": "white" if ply % 2 else "black",
                "san": san,
                "uci": move.uci(),
                "fen_before": before,
                "fen_after": board.fen(),
                "is_player_move": True,
            }
        )
    return moves


SICILIAN = ["e4", "c5", "Nf3", "d6", "d4", "cxd4"]
ITALIAN = ["e4", "e5", "Nf3", "Nc6", "Bc4", "Bc5"]


def _seed() -> None:
    with session_scope() as session:
        player = PlayerRow(platform=PLATFORM, username=USERNAME, username_normalized=USERNAME)
        session.add(player)
        session.flush()
        specs = [
            # (id, white, black, color, result, date, time control, moves, elo)
            ("g1", USERNAME, "alice", "white", "win", "2026.01.05", "600", ITALIAN, 500),
            ("g2", "bob", USERNAME, "black", "loss", "2026.02.10", "180", SICILIAN, 480),
            ("g3", USERNAME, "alice", "white", "draw", "2026.03.15", "600", SICILIAN, 520),
            ("g4", "carol", USERNAME, "black", "win", "2026.03.20", "60", ITALIAN, 400),
            # Junk: no players, unknown date. Hidden everywhere.
            ("junk", "?", "?", "unknown", "unknown", "????.??.??", "", ITALIAN, None),
            # No moves: cannot be reviewed. Hidden too.
            ("empty", USERNAME, "dave", "white", "win", "2026.03.21", "600", [], 530),
        ]
        rows = {}
        for game_id, white, black, color, result, date, tc, sans, elo in specs:
            row = GameRow(
                player_id=player.id,
                external_game_id=game_id,
                white=white,
                black=black,
                result="1-0",
                player_result=result,
                player_color=color,
                player_elo=elo,
                played_at=date,
                time_control=tc,
                link=f"https://www.chess.com/game/live/{len(rows) + 1}",
                metadata_json={"game": {"eco": "C50"}, "moves": _moves(sans)},
            )
            session.add(row)
            session.flush()
            session.add(AnalysisRow(game_id=row.id, summary="", training_plan=[], retrieval_notes=[]))
            rows[game_id] = row
        moments = [
            ("g1", "missed_tactic", "blunder", 0.4),
            ("g1", "missed_tactic", "mistake", 0.2),
            ("g2", "missed_tactic", "blunder", 0.5),
            ("g3", "loose_piece", "mistake", 0.3),
        ]
        for index, (game_id, theme, judgment, severity) in enumerate(moments):
            fen = rows[game_id].metadata_json["moves"][2]["fen_before"]
            session.add(
                CriticalMomentRow(
                    game_id=rows[game_id].id,
                    external_moment_id=f"{game_id}-{index}",
                    move_number=2,
                    ply=3,
                    phase="opening",
                    theme=theme,
                    played_san="Nf3",
                    best_san="d4",
                    fen_before=fen,
                    fen_after=fen,
                    severity=severity,
                    explanation={"judgment": judgment, "trainable": True},
                )
            )
        plan = TrainingPlanRow(player_id=player.id, focus_themes=["missed_tactic"], difficulty="beginner")
        session.add(plan)
        session.flush()
        position = TrainingPositionRow(
            plan_id=plan.id,
            position_order=1,
            fen=chess.STARTING_FEN,
            correct_move="e4",
            theme="missed_tactic",
            difficulty="beginner",
        )
        session.add(position)
        session.flush()
        session.add(
            ReviewScheduleRow(
                player_id=player.id,
                position_id=position.id,
                due_at=datetime.now(UTC) - timedelta(days=1),
            )
        )


_seed()
client = TestClient(app)
BASE = f"/api/library/{PLATFORM}/{USERNAME}"


def test_library_hides_junk_and_sorts_newest_first():
    page = client.get(BASE).json()
    assert page["library_total"] == 4
    assert page["total"] == 4
    ids = [item["game_id"] for item in page["items"]]
    assert ids == ["g4", "g3", "g2", "g1"]
    assert "junk" not in ids and "empty" not in ids
    first = page["items"][0]
    assert first["date"] == "2026-03-20"
    assert first["opponent"] == "carol"
    assert first["time_class"] == "bullet"
    assert first["move_count"] == 3
    assert page["facets"]["results"] == {"win": 2, "loss": 1, "draw": 1}


def test_library_payload_is_light_and_paginated():
    response = client.get(BASE, params={"limit": 2})
    page = response.json()
    assert len(page["items"]) == 2 and page["has_more"] is True
    assert "moves" not in page["items"][0]
    rest = client.get(BASE, params={"limit": 2, "offset": 2}).json()
    assert [item["game_id"] for item in rest["items"]] == ["g2", "g1"]
    assert rest["has_more"] is False


def test_library_filters():
    def ids(**params):
        return [item["game_id"] for item in client.get(BASE, params=params).json()["items"]]

    assert ids(result="win") == ["g4", "g1"]
    assert ids(color="black") == ["g4", "g2"]
    assert ids(time_class="rapid") == ["g3", "g1"]
    assert ids(q="ALI") == ["g3", "g1"]
    assert ids(opening="Sicilian Defense") == ["g3", "g2"]
    # g1 and g2 have one blunder each; g1 also has a mistake.
    assert ids(sort="blunders")[:2] == ["g1", "g2"]
    # Games with at least one critical moment of the theme.
    assert ids(theme="missed_tactic") == ["g2", "g1"]
    assert ids(theme="loose_piece", result="draw") == ["g3"]
    assert ids(theme="no_such_theme") == []


def test_library_page_counts_moments_and_names_openings():
    items = {item["game_id"]: item for item in client.get(BASE).json()["items"]}
    assert items["g1"]["moment_count"] == 2
    assert items["g1"]["blunders"] == 1 and items["g1"]["mistakes"] == 1
    assert items["g1"]["top_themes"] == ["missed_tactic"]
    assert items["g2"]["opening_family"] == "Sicilian Defense"


def test_unknown_player_returns_empty_library():
    page = client.get(f"/api/library/{PLATFORM}/nobody-here").json()
    assert page["library_total"] == 0 and page["items"] == []


def test_progress_splits_rating_by_time_control_and_reports_share_of_games():
    progress = client.get(f"{BASE}/progress").json()
    assert progress["total_games"] == 4
    series = progress["rating_series"]
    assert [point["rating"] for point in series["rapid"]] == [500, 520]
    assert series["blitz"] == [{"date": "2026-02-10", "rating": 480}]
    blindspots = {item["theme"]: item for item in progress["blindspots"]}
    # Three moments, but only two of the four games.
    assert blindspots["missed_tactic"]["moments"] == 3
    assert blindspots["missed_tactic"]["games"] == 2
    assert blindspots["missed_tactic"]["pct_of_games"] == 50.0


def test_practice_queue_previews_first_position():
    queue = client.get(f"{BASE}/practice-queue").json()
    assert queue["due_count"] == 1
    assert queue["due_themes"] == [{"name": "missed_tactic", "count": 1}]
    assert queue["candidate_count"] == 4
    assert queue["preview"]["game_id"] == "g2"  # highest severity
    assert queue["preview"]["opponent"] == "bob"


def test_opening_position_lookup():
    found = client.get("/api/library/opening-position", params={"name": "Sicilian Defense"}).json()
    board = chess.Board(found["fen"])
    assert board.piece_at(chess.C5) is not None
    assert client.get("/api/library/opening-position", params={"name": "Not an opening"}).status_code == 404


def test_index_rebuilds_when_games_change():
    client.get(BASE)
    with session_scope() as session:
        player = library_api._find_player(session, PLATFORM, USERNAME)
        assert player is not None
        session.add(
            GameRow(
                player_id=player.id,
                external_game_id="g5",
                white=USERNAME,
                black="erin",
                result="1-0",
                player_result="win",
                player_color="white",
                played_at="2026.04.01",
                time_control="600",
                metadata_json={"moves": _moves(ITALIAN)},
            )
        )
    page = client.get(BASE).json()
    assert page["library_total"] == 5
    assert page["items"][0]["game_id"] == "g5"
