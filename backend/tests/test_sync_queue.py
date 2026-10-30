"""The durable game sync queue: claiming, heartbeats, retries and shutdown."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.dialects import postgresql

from chess_coach_agent import adaptive_api, sync_queue
from chess_coach_agent.agent import sample_pgn
from chess_coach_agent.db import session_scope
from chess_coach_agent.db_models import SyncJobRow
from chess_coach_agent.repositories import get_or_create_player
from chess_coach_agent.sync_queue import (
    MAX_ATTEMPTS,
    STALE_AFTER,
    SyncWorker,
    claim_next,
    heartbeat,
    release,
)


@pytest.fixture(autouse=True)
def empty_queue():
    """Jobs are shared across the test database, and a claim takes the oldest."""
    with session_scope() as session:
        session.execute(
            update(SyncJobRow)
            .where(SyncJobRow.status.in_(sync_queue.ACTIVE_STATUSES))
            .values(status="failed")
        )


def _job(**fields) -> str:
    with session_scope() as session:
        username = f"queue-{uuid4().hex[:8]}"
        player = get_or_create_player(session, "lichess", username)
        job = SyncJobRow(player_id=player.id, platform="lichess", username=username, **fields)
        session.add(job)
        session.flush()
        return job.id


def _row(job_id: str) -> SyncJobRow:
    with session_scope() as session:
        return session.get_one(SyncJobRow, job_id)


def _long_ago() -> datetime:
    return datetime.now(UTC) - STALE_AFTER - timedelta(seconds=5)


def test_claim_compiles_to_skip_locked_on_postgres():
    sql = str(sync_queue._next_claimable().compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in sql


def test_claim_takes_each_job_once_oldest_first():
    first = _job(max_games=7)
    second = _job()
    lease = claim_next("worker-a")
    assert lease.job_id == first
    assert lease.attempt == 1
    assert lease.request.max_games == 7
    assert claim_next("worker-b").job_id == second
    assert claim_next("worker-c") is None
    row = _row(first)
    assert (row.status, row.worker_id, row.attempts) == ("fetching", "worker-a", 1)
    assert row.heartbeat_at is not None


def test_parallel_workers_cannot_claim_the_same_job():
    """SQLite ignores FOR UPDATE, so here only the compare-and-swap stands between them."""
    job_id = _job()
    with ThreadPoolExecutor(max_workers=8) as pool:
        leases = list(pool.map(claim_next, [f"worker-{slot}" for slot in range(8)]))
    assert [lease.job_id for lease in leases if lease] == [job_id]
    assert _row(job_id).attempts == 1


def test_healthy_running_job_is_left_alone():
    job_id = _job()
    claim_next("worker-a")
    assert claim_next("worker-b") is None
    assert _row(job_id).worker_id == "worker-a"


def test_job_without_a_heartbeat_is_reclaimed():
    job_id = _job(status="analyzing", worker_id="dead", attempts=1, heartbeat_at=_long_ago())
    lease = claim_next("worker-b")
    assert lease.job_id == job_id
    assert lease.attempt == 2
    assert _row(job_id).worker_id == "worker-b"


def test_job_from_before_heartbeats_is_judged_by_updated_at():
    job_id = _job(status="analyzing", updated_at=_long_ago())
    assert claim_next("worker").job_id == job_id


def test_job_out_of_attempts_fails_and_the_next_one_runs():
    dead = _job(status="analyzing", attempts=MAX_ATTEMPTS, heartbeat_at=_long_ago())
    waiting = _job()
    assert claim_next("worker").job_id == waiting
    row = _row(dead)
    assert row.status == "failed"
    assert "interrupted" in row.error


def test_heartbeat_fails_once_the_job_is_taken_over():
    _job()
    lease = claim_next("worker-a")
    assert heartbeat(lease)
    with session_scope() as session:
        session.execute(
            update(SyncJobRow)
            .where(SyncJobRow.id == lease.job_id)
            .values(heartbeat_at=_long_ago())
        )
    assert claim_next("worker-b").job_id == lease.job_id
    assert not heartbeat(lease)


def test_release_requeues_without_spending_the_attempt():
    job_id = _job()
    lease = claim_next("worker-a")
    release(lease)
    row = _row(job_id)
    assert (row.status, row.worker_id, row.attempts) == ("queued", None, 0)


def test_worker_runs_a_job_and_finishes(monkeypatch):
    job_id = _job()
    seen = []

    async def handler(claimed_id, request):
        seen.append((claimed_id, request.username))
        with session_scope() as session:
            session.get_one(SyncJobRow, claimed_id).status = "complete"

    async def scenario():
        worker = SyncWorker(handler)
        worker.start()
        worker.notify()
        for _ in range(500):
            if seen and _row(job_id).status == "complete":
                break
            await asyncio.sleep(0.01)
        await worker.stop()

    asyncio.run(scenario())
    assert _row(job_id).status == "complete"


def test_shutdown_puts_the_running_job_back(monkeypatch):
    job_id = _job()
    started = []

    async def handler(_job_id, _request):
        started.append(True)
        await asyncio.sleep(60)

    async def scenario():
        worker = SyncWorker(handler)
        worker.start()
        for _ in range(500):
            if started:
                break
            await asyncio.sleep(0.01)
        await worker.stop()

    asyncio.run(scenario())
    assert (_row(job_id).status, _row(job_id).attempts) == ("queued", 0)


def test_worker_that_loses_its_job_stops_working_on_it(monkeypatch):
    monkeypatch.setattr(sync_queue, "HEARTBEAT_SECONDS", 0.01)
    job_id = _job()
    cancelled = []

    async def handler(_job_id, _request):
        with session_scope() as session:
            session.get_one(SyncJobRow, job_id).worker_id = "someone-else"
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    async def scenario():
        lease = claim_next("worker-a")
        await asyncio.wait_for(SyncWorker(handler).run_leased(lease), 5)

    asyncio.run(scenario())
    assert cancelled


def test_retried_job_counts_each_game_once(monkeypatch):
    """A retry finds what the lost attempt stored. Those games are in analyzed_games already,
    so analyzed + skipped must still come to the total."""

    async def fetch(*_):
        return sample_pgn()

    monkeypatch.setattr(adaptive_api, "fetch_platform_pgn", fetch)
    username = f"retry-{uuid4().hex[:8]}"

    def run(job_id, request):
        asyncio.run(adaptive_api.process_sync_job(job_id, request))

    with session_scope() as session:
        player = get_or_create_player(session, "chess.com", username)
        job = SyncJobRow(player_id=player.id, platform="chess.com", username=username, max_games=2)
        session.add(job)
        session.flush()
        job_id = job.id

    request = sync_queue.SyncGamesRequest(platform="chess.com", username=username, max_games=2)
    run(job_id, request)
    finished = _row(job_id)
    assert finished.status == "complete"
    total = finished.total_games
    assert finished.analyzed_games == total

    with session_scope() as session:  # as if the worker died at the very end of the job
        session.get_one(SyncJobRow, job_id).status = "analyzing"
    run(job_id, request)
    retried = _row(job_id)
    assert retried.status == "complete"
    assert (retried.analyzed_games, retried.skipped_games) == (total, 0)
