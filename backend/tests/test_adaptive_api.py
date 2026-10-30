import time
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from chess_coach_agent.api import app
from chess_coach_agent.db import session_scope
from chess_coach_agent.db_models import ReviewScheduleRow, SyncJobRow, TrainingPositionRow
from chess_coach_agent.importers import ImportSourceError, preview_pgn_games
from chess_coach_agent.repositories import get_or_create_player


def test_persistent_training_and_progress_flow(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with TestClient(app) as client:
        sample = client.get("/api/sample").json()
        analysis = client.post(
            "/api/analyze",
            json={
                "pgn": sample["pgn"],
                "player": "kfctofu",
                "platform": "chess.com",
                "max_games": 1,
            },
        )
        assert analysis.status_code == 200
        analyzed_moment = analysis.json()["analyses"][0]["moments"][0]

        exact_training = client.post(
            "/api/training/sessions",
            json={
                "platform": "chess.com",
                "username": "kfctofu",
                "theme": analyzed_moment["theme"],
                "moment_id": analyzed_moment["id"],
                "position_count": 1,
            },
        )
        assert exact_training.status_code == 200
        assert len(exact_training.json()["positions"]) == 1
        assert exact_training.json()["positions"][0]["fen"] == analyzed_moment["fen_before"]

        training = client.post(
            "/api/training/sessions",
            json={"platform": "chess.com", "username": "kfctofu", "position_count": 3},
        )
        assert training.status_code == 200
        payload = training.json()
        assert payload["positions"]
        position = payload["positions"][0]
        with session_scope() as session:
            move = session.get(TrainingPositionRow, position["id"]).correct_move
        assert move in position["choices"] or not position["choices"]
        attempt = client.post(
            f"/api/training/sessions/{payload['id']}/attempts",
            json={"position_id": position["id"], "move": move, "elapsed_ms": 1200},
        )
        assert attempt.status_code == 200
        assert attempt.json()["legal"] is True
        with session_scope() as session:
            schedule = session.scalar(
                select(ReviewScheduleRow).where(
                    ReviewScheduleRow.position_id == position["id"]
                )
            )
            assert schedule is not None
            assert schedule.interval_days == 7

        hinted = client.post(
            f"/api/training/sessions/{payload['id']}/attempts",
            json={
                "position_id": position["id"],
                "move": move,
                "hints_used": 1,
                "elapsed_ms": 900,
            },
        )
        assert hinted.status_code == 200
        with session_scope() as session:
            schedule = session.scalar(
                select(ReviewScheduleRow).where(
                    ReviewScheduleRow.position_id == position["id"]
                )
            )
            assert schedule is not None
            assert schedule.interval_days == 3

        progress = client.get("/api/progress/chess.com/kfctofu")
        assert progress.status_code == 200
        assert progress.json()["total_games"] >= 1
        assert progress.json()["recent_attempts"] >= 2


def test_full_history_sync_deduplicates_analyzed_games(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with TestClient(app) as client:
        sample = client.get("/api/sample").json()
        one_game_pgn = preview_pgn_games(
            sample["pgn"], "kfctofu", "chess.com", max_games=1
        )[0].pgn

        async def sample_history(
            _platform: str, _username: str, _max_games: int
        ) -> str:
            return one_game_pgn

        monkeypatch.setattr(
            "chess_coach_agent.adaptive_api.fetch_platform_pgn", sample_history
        )
        analyzed = client.post(
            "/api/analyze",
            json={
                "pgn": one_game_pgn,
                "player": "kfctofu",
                "platform": "chess.com",
                "max_games": 1,
            },
        )
        assert analyzed.status_code == 200

        started = client.post(
            "/api/games/sync",
            json={"platform": "chess.com", "username": "kfctofu", "max_games": 5000},
        )
        assert started.status_code == 200
        payload = _finished_job(client, started.json()["id"])
        assert payload["status"] == "complete"
        assert payload["total_games"] == 1
        assert payload["analyzed_games"] == 0
        assert payload["skipped_games"] == 1


def _sample_games(client: TestClient, count: int) -> list[str]:
    sample = client.get("/api/sample").json()
    return [
        game.pgn
        for game in preview_pgn_games(sample["pgn"], "kfctofu", "chess.com", max_games=count)
    ]


def _finished_job(client: TestClient, job_id: str) -> dict:
    """Poll as the frontend does, while the worker started with the app runs the job."""
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        job = client.get(f"/api/games/sync/{job_id}")
        assert job.status_code == 200
        if job.json()["status"] in {"complete", "failed"}:
            return job.json()
        time.sleep(0.02)
    raise AssertionError(f"Sync job did not finish: {job.json()}")


def _run_sync(client: TestClient, username: str, platform: str = "chess.com") -> dict:
    started = client.post(
        "/api/games/sync",
        json={"platform": platform, "username": username, "max_games": 50},
    )
    assert started.status_code == 200
    return _finished_job(client, started.json()["id"])


def test_sync_failure_reports_readable_error(monkeypatch):
    async def missing_player(_platform: str, username: str, _max_games: int) -> str:
        raise ImportSourceError(f"Lichess player '{username}' was not found.")

    async def network_down(_platform: str, _username: str, _max_games: int) -> str:
        raise ConnectionError()

    with TestClient(app) as client:
        monkeypatch.setattr("chess_coach_agent.adaptive_api.fetch_platform_pgn", missing_player)
        payload = _run_sync(client, "nobody-here", "lichess")
        assert payload["status"] == "failed"
        assert payload["error"] == "Lichess player 'nobody-here' was not found."

        monkeypatch.setattr("chess_coach_agent.adaptive_api.fetch_platform_pgn", network_down)
        payload = _run_sync(client, "nobody-here", "lichess")
        assert payload["status"] == "failed"
        assert payload["error"] == "ConnectionError"


def test_sync_rejects_blank_username():
    with TestClient(app) as client:
        response = client.post(
            "/api/games/sync", json={"platform": "lichess", "username": "   "}
        )
        assert response.status_code == 422


def test_sync_continues_past_a_game_that_fails_to_analyze(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with TestClient(app) as client:
        games = _sample_games(client, 3)

        async def history(_platform: str, _username: str, _max_games: int) -> str:
            return "\n\n".join(games)

        from chess_coach_agent.adaptive_api import coach_agent

        original = coach_agent.import_pgn_text
        broken = games[1]

        def flaky_import(pgn: str, player: str, max_games: int = 1):
            if pgn == broken:
                raise RuntimeError("engine crashed")
            return original(pgn, player, max_games)

        monkeypatch.setattr("chess_coach_agent.adaptive_api.fetch_platform_pgn", history)
        monkeypatch.setattr(coach_agent, "import_pgn_text", flaky_import)
        payload = _run_sync(client, "flaky-sync-player")
        assert payload["status"] == "complete"
        assert payload["total_games"] == 3
        assert payload["analyzed_games"] == 2
        assert payload["skipped_games"] == 1
        assert "1 game(s) could not be analyzed" in payload["error"]

        # The failed game is retried by the next sync; the analyzed ones are skipped.
        monkeypatch.setattr(coach_agent, "import_pgn_text", original)
        payload = _run_sync(client, "Flaky-Sync-Player")
        assert payload["status"] == "complete"
        assert payload["analyzed_games"] == 1
        assert payload["skipped_games"] == 2


def test_interrupted_sync_job_is_resumed_not_replaced(monkeypatch):
    async def empty_history(_platform: str, _username: str, _max_games: int) -> str:
        return ""

    monkeypatch.setattr("chess_coach_agent.adaptive_api.fetch_platform_pgn", empty_history)
    with session_scope() as session:
        player = get_or_create_player(session, "chess.com", "stale-sync-player")
        stale = SyncJobRow(
            player_id=player.id,
            platform="chess.com",
            username="stale-sync-player",
            status="analyzing",
            worker_id="dead-worker",
            attempts=1,
            heartbeat_at=datetime.now(UTC) - timedelta(hours=1),
        )
        session.add(stale)
        session.flush()
        stale_id = stale.id

    with TestClient(app) as client:
        started = client.post(
            "/api/games/sync", json={"platform": "chess.com", "username": "stale-sync-player"}
        )
        assert started.json()["id"] == stale_id
        assert _finished_job(client, stale_id)["status"] == "complete"


def test_pasted_pgn_without_games_is_rejected():
    with TestClient(app) as client:
        response = client.post(
            "/api/analyze",
            json={"pgn": "hello world", "player": "kfctofu", "platform": "chess.com"},
        )
        assert response.status_code == 422
        assert "No games" in response.json()["detail"]


def test_pasted_headerless_games_are_stored_separately(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with TestClient(app) as client:
        response = client.post(
            "/api/analyze",
            json={
                "pgn": "1. e4 e5 2. Nf3 Nc6 *\n\n1. d4 d5 2. c4 *",
                "player": "headerless-paster",
                "platform": "chess.com",
                "max_games": 20,
            },
        )
        assert response.status_code == 200
        ids = {item["game"]["game_id"] for item in response.json()["analyses"]}
        assert len(ids) == 2
        stored = client.get("/api/games/chess.com/headerless-paster").json()["analyses"]
        assert {item["game"]["game_id"] for item in stored} == ids


def test_single_stored_game_can_be_loaded_by_id(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with TestClient(app) as client:
        games = _sample_games(client, 2)
        analyzed = client.post(
            "/api/analyze",
            json={
                "pgn": "\n\n".join(games),
                "player": "kfctofu",
                "platform": "chess.com",
                "max_games": 2,
            },
        ).json()["analyses"]
        wanted = analyzed[1]["game"]["game_id"]
        response = client.get(f"/api/games/chess.com/KFCTOFU?game_id={wanted}")
        assert response.status_code == 200
        assert [item["game"]["game_id"] for item in response.json()["analyses"]] == [wanted]


def test_sync_skips_stored_game_after_opponent_renamed(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    original = (
        '[Event "Live Chess"]\n[Site "Chess.com"]\n[Date "2024.02.26"]\n'
        '[White "rename-tester"]\n[Black "oldname"]\n[Result "1-0"]\n'
        '[Link "https://www.chess.com/game/live/102650401443"]\n\n'
        "1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0\n"
    )
    renamed = original.replace('"oldname"', '"newname"')

    async def history(_platform: str, _username: str, _max_games: int) -> str:
        return renamed

    with TestClient(app) as client:
        stored = client.post(
            "/api/analyze",
            json={"pgn": original, "player": "rename-tester", "platform": "chess.com"},
        )
        assert stored.status_code == 200
        monkeypatch.setattr("chess_coach_agent.adaptive_api.fetch_platform_pgn", history)
        payload = _run_sync(client, "rename-tester")
        assert payload["status"] == "complete"
        assert payload["skipped_games"] == 1
        assert payload["analyzed_games"] == 0

        # Re-importing the renamed copy updates the stored game instead of duplicating it.
        reimported = client.post(
            "/api/analyze",
            json={"pgn": renamed, "player": "rename-tester", "platform": "chess.com"},
        )
        assert reimported.status_code == 200
        games = client.get("/api/games/chess.com/rename-tester").json()["analyses"]
        assert len(games) == 1
        assert games[0]["game"]["black"] == "newname"
        assert games[0]["game"]["game_id"] == reimported.json()["analyses"][0]["game"]["game_id"]
