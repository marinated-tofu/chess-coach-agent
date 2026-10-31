"""Race real workers for sync jobs on Postgres, which the SQLite test suite cannot do.

Needs DATABASE_URL pointing at a migrated Postgres database. CI runs it.
"""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from sqlalchemy import func, select

from chess_coach_agent.db import engine, session_scope
from chess_coach_agent.db_models import SyncJobRow
from chess_coach_agent.repositories import get_or_create_player
from chess_coach_agent.sync_queue import claim_next

JOBS = 200
WORKERS = 8


def add_job() -> str:
    with session_scope() as session:
        username = f"queue-{uuid4().hex[:8]}"
        player = get_or_create_player(session, "lichess", username)
        job = SyncJobRow(player_id=player.id, platform="lichess", username=username)
        session.add(job)
        session.flush()
        return job.id


def finish(job_id: str) -> None:
    with session_scope() as session:
        session.get_one(SyncJobRow, job_id).status = "completed"


def check_skip_locked() -> None:
    """A claim must step past a row another transaction holds, not wait for it."""
    held, free = add_job(), add_job()
    with session_scope() as session:
        session.execute(select(SyncJobRow).where(SyncJobRow.id == held).with_for_update())
        with ThreadPoolExecutor(max_workers=1) as pool:
            lease = pool.submit(claim_next, "skip-locked").result(timeout=5)
    assert lease and lease.job_id == free, f"expected {free}, got {lease}"
    finish(free)
    finish(held)


def check_race() -> None:
    jobs = {add_job() for _ in range(JOBS)}
    start = Barrier(WORKERS)

    def work(slot: int) -> list[str]:
        start.wait()
        claimed = []
        while lease := claim_next(f"worker-{slot}"):
            claimed.append(lease.job_id)
            finish(lease.job_id)
        return claimed

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        per_worker = list(pool.map(work, range(WORKERS)))

    claims = Counter(job for claimed in per_worker for job in claimed)
    assert set(claims) == jobs, f"{len(jobs - set(claims))} jobs were never claimed"
    assert max(claims.values()) == 1, "a job was claimed twice"
    busy = sum(1 for claimed in per_worker if claimed)
    assert busy > 1, "only one worker got jobs, so nothing raced"
    with session_scope() as session:
        attempts = session.scalar(
            select(func.max(SyncJobRow.attempts)).where(SyncJobRow.id.in_(jobs))
        )
    assert attempts == 1, f"a job spent {attempts} attempts"
    print(f"{JOBS} jobs claimed once each across {busy} workers: {[len(c) for c in per_worker]}")


if __name__ == "__main__":
    assert engine.dialect.name == "postgresql", "this check needs Postgres"
    check_skip_locked()
    check_race()
    print("Postgres queue check passed")
