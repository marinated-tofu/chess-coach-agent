from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from chess_coach_agent.api import app
from chess_coach_agent.db import session_scope
from chess_coach_agent.db_models import (
    AnalysisRow,
    CriticalMomentRow,
    GameRow,
    ReviewScheduleRow,
    SyncJobRow,
    TrainingPlanRow,
    TrainingPositionRow,
)
from chess_coach_agent.repositories import get_or_create_player

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
client = TestClient(app)
# One real move: the library (and so Today's count) hides games with no moves.
E4 = {
    "ply": 1,
    "move_number": 1,
    "color": "white",
    "san": "e4",
    "uci": "e2e4",
    "fen_before": START_FEN,
    "fen_after": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
    "is_player_move": True,
}


def _game(player_id: str, number: int, played_at: str, tc: str, elo: int | None, game_id: int) -> GameRow:
    return GameRow(
        player_id=player_id,
        external_game_id=f"g{number}",
        white="me",
        black=f"opp{number}",
        result="1-0",
        player_result="win",
        player_color="white",
        player_elo=elo,
        played_at=played_at,
        time_control=tc,
        link=f"https://www.chess.com/game/live/{game_id}",
        metadata_json={"game": {}, "moves": [E4]},
    )


def _seed(username: str) -> None:
    now = datetime.now(UTC)
    with session_scope() as session:
        player = get_or_create_player(session, "chess.com", username)
        player.current_rating = 1  # whatever the last sync batch wrote; Today must not use it
        # Same-day blitz games stored newest-first: created_at alone would pick the older one.
        newest = _game(player.id, 1, "2026.06.22", "300", 812, 900)
        session.add(newest)
        session.flush()
        session.add(_game(player.id, 2, "2026.06.22", "300", 790, 800))
        session.add(_game(player.id, 3, "2026.06.20", "600", 950, 700))
        session.add(_game(player.id, 4, "2026.06.21", "60", None, 750))
        session.add(_game(player.id, 5, "????.??.??", "", 400, 999))
        session.flush()
        session.add(AnalysisRow(game_id=newest.id, summary="s", training_plan=[], retrieval_notes=[]))
        for ply, judgment in ((14, "mistake"), (9, "blunder"), (21, "blunder")):
            session.add(
                CriticalMomentRow(
                    game_id=newest.id,
                    external_moment_id=f"g1-{ply}",
                    move_number=(ply + 1) // 2,
                    ply=ply,
                    phase="opening",
                    theme="missed_tactic",
                    played_san="Nf3",
                    best_san="Bb5",
                    fen_before=START_FEN,
                    fen_after=START_FEN,
                    severity=0.3,
                    explanation={"judgment": judgment},
                )
            )
        plan = TrainingPlanRow(player_id=player.id)
        session.add(plan)
        session.flush()
        for order, (theme, offset) in enumerate(
            (("missed_tactic", -2), ("missed_tactic", -1), ("loose_piece", -1), ("loose_piece", 3))
        ):
            position = TrainingPositionRow(
                plan_id=plan.id,
                position_order=order,
                fen=START_FEN,
                correct_move="e4",
                theme=theme,
                difficulty="intermediate",
            )
            session.add(position)
            session.flush()
            session.add(
                ReviewScheduleRow(
                    player_id=player.id, position_id=position.id, due_at=now + timedelta(days=offset)
                )
            )
        session.add(
            SyncJobRow(player_id=player.id, platform="chess.com", username=username, status="complete")
        )


def test_today_unknown_player_is_empty_and_not_created():
    body = client.get("/api/today/lichess/nobody-at-all").json()
    assert body["known"] is False
    assert body["total_games"] == 0
    assert body["current_rating"] == {}
    assert body["latest_game"] is None
    assert body["due"]["count"] == 0
    # A read must not create the player.
    assert client.get("/api/today/lichess/nobody-at-all").json()["known"] is False


def test_today_summary_counts_ratings_due_and_latest_game():
    _seed("today-user")
    body = client.get("/api/today/chess.com/Today-User").json()

    assert body["known"] is True
    assert body["total_games"] == 5
    # Latest game per time control; same-day ties broken by the Chess.com game id.
    assert body["current_rating"] == {"blitz": 812, "rapid": 950}
    assert body["last_synced_at"] is not None

    due = body["due"]
    assert due["count"] == 3
    assert due["themes"] == [
        {"theme": "missed_tactic", "count": 2},
        {"theme": "loose_piece", "count": 1},
    ]
    assert due["next_due_at"] is not None

    latest = body["latest_game"]
    assert latest["game_id"] == "g1"
    assert latest["opponent"] == "opp1"
    assert latest["time_category"] == "blitz"
    assert latest["blunders"] == 2
    assert latest["mistakes"] == 1
    assert latest["first_moment"]["ply"] == 9
    assert latest["first_moment"]["id"] == "g1-9"


def test_today_rating_is_stable_across_calls():
    first = client.get("/api/today/chess.com/today-user").json()["current_rating"]
    second = client.get("/api/today/chess.com/today-user").json()["current_rating"]
    assert first == second
