"""Durable queue for game syncs, kept in the sync_jobs table.

POST /api/games/sync only writes a queued row. A worker claims rows and runs them, one at a time
per slot, and heartbeats while it does. If the process dies, the heartbeat stops and any worker
reclaims the job after STALE_AFTER. Retrying is safe because a sync skips games already stored.

Claiming uses FOR UPDATE SKIP LOCKED on Postgres. SQLite ignores that clause, so the claim itself
is a compare-and-swap on `attempts`, which holds on both databases. `attempts` also identifies
the lease: a worker that loses its job finds out at its next heartbeat and stops.

The worker runs inside the app process by default. To run it apart from the web server, set
SYNC_WORKER_ENABLED=false on the web server and start `python -m chess_coach_agent.sync_queue`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select, update

from .db import session_scope
from .db_models import SyncJobRow
from .models import SyncGamesRequest
from .monitoring import log_event

logger = logging.getLogger(__name__)

RUNNING_STATUSES = ("fetching", "analyzing")
ACTIVE_STATUSES = ("queued", *RUNNING_STATUSES)
HEARTBEAT_SECONDS = 20.0
# Long enough to ride out an event loop blocked by a slow request.
STALE_AFTER = timedelta(minutes=2)
POLL_SECONDS = 5.0
# A job that keeps taking its worker down (out of memory, say) must not do so forever.
MAX_ATTEMPTS = 5
GAVE_UP_MESSAGE = "Sync was interrupted too many times. Start it again to resume."

Handler = Callable[[str, SyncGamesRequest], Awaitable[None]]


@dataclass(frozen=True)
class Lease:
    job_id: str
    worker_id: str
    attempt: int
    request: SyncGamesRequest


def _now() -> datetime:
    return datetime.now(UTC)


def claimable():
    """Queued jobs, and running jobs whose worker stopped heartbeating. Rows from before
    heartbeats, or claimed by an older release, are judged by updated_at."""
    last_alive = func.coalesce(SyncJobRow.heartbeat_at, SyncJobRow.updated_at)
    return or_(
        SyncJobRow.status == "queued",
        and_(SyncJobRow.status.in_(RUNNING_STATUSES), last_alive < _now() - STALE_AFTER),
    )


def _next_claimable():
    return (
        select(SyncJobRow)
        .where(claimable())
        .order_by(SyncJobRow.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )


def claim_next(worker_id: str) -> Lease | None:
    """Take the oldest available job, or None. Jobs out of attempts are failed on the way."""
    while True:
        with session_scope() as session:
            job = session.scalar(_next_claimable())
            if job is None:
                return None
            seen = job.attempts
            if seen >= MAX_ATTEMPTS:
                job.status = "failed"
                job.error = GAVE_UP_MESSAGE
                log_event("games_sync_failed", {"job_id": job.id, "error": GAVE_UP_MESSAGE})
                continue
            claimed = session.execute(
                update(SyncJobRow)
                .where(SyncJobRow.id == job.id, SyncJobRow.attempts == seen)
                .values(
                    status="fetching",
                    worker_id=worker_id,
                    attempts=seen + 1,
                    heartbeat_at=_now(),
                )
            )
            if claimed.rowcount != 1:  # another worker got there first (SQLite)
                continue
            lease = Lease(
                job_id=job.id,
                worker_id=worker_id,
                attempt=seen + 1,
                request=SyncGamesRequest(
                    platform=job.platform, username=job.username, max_games=job.max_games
                ),
            )
        if lease.attempt > 1:
            log_event("games_sync_retried", {"job_id": lease.job_id, "attempt": lease.attempt})
        return lease


def _held(lease: Lease):
    return and_(
        SyncJobRow.id == lease.job_id,
        SyncJobRow.worker_id == lease.worker_id,
        SyncJobRow.attempts == lease.attempt,
        SyncJobRow.status.in_(RUNNING_STATUSES),
    )


def heartbeat(lease: Lease) -> bool:
    """Prove the worker is alive. False means the job is no longer ours to run."""
    with session_scope() as session:
        return session.execute(
            update(SyncJobRow).where(_held(lease)).values(heartbeat_at=_now())
        ).rowcount == 1


def release(lease: Lease) -> None:
    """Hand a job back on a clean shutdown, so the next worker needn't wait for it to go stale.
    Being shut down is not the job's fault, so the attempt doesn't count."""
    with session_scope() as session:
        session.execute(
            update(SyncJobRow)
            .where(_held(lease))
            .values(status="queued", worker_id=None, heartbeat_at=None, attempts=lease.attempt - 1)
        )


class SyncWorker:
    """Claim-and-run loops. Several slots keep one long sync from holding up everyone else's."""

    def __init__(self, handler: Handler, slots: int = 1) -> None:
        self.handler = handler
        self.slots = slots
        self.id = f"{socket.gethostname()[:60]}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.stopping = False
        self._wake = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self.run_loop(f"{self.id}/{slot}")) for slot in range(self.slots)
        ]

    async def stop(self) -> None:
        self.stopping = True
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def notify(self) -> None:
        self._wake.set()

    async def _idle(self) -> None:
        try:
            await asyncio.wait_for(self._wake.wait(), POLL_SECONDS)
        except TimeoutError:
            pass
        self._wake.clear()

    async def run_loop(self, worker_id: str) -> None:
        while not self.stopping:
            try:
                lease = await asyncio.to_thread(claim_next, worker_id)
            except Exception:
                logger.exception("Could not claim a sync job")
                lease = None
            if lease is None:
                await self._idle()
            else:
                await self.run_leased(lease)

    async def run_leased(self, lease: Lease) -> None:
        lost = asyncio.Event()
        work = asyncio.create_task(self.handler(lease.job_id, lease.request))
        beat = asyncio.create_task(self._keep_alive(lease, work, lost))
        try:
            await work
        except asyncio.CancelledError:
            if not lost.is_set():  # shutting down, not lost to another worker
                work.cancel()
                await asyncio.gather(work, return_exceptions=True)
                release(lease)
                raise
            logger.warning("Lost sync job %s to another worker", lease.job_id)
        except Exception:
            # The handler records its own failures, so the database is probably down. Leave the
            # job to go stale and be retried.
            logger.exception("Sync job %s stopped unexpectedly", lease.job_id)
        finally:
            beat.cancel()

    async def _keep_alive(self, lease: Lease, work: asyncio.Task, lost: asyncio.Event) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            try:
                held = await asyncio.to_thread(heartbeat, lease)
            except Exception:
                logger.exception("Sync job %s heartbeat failed", lease.job_id)
                continue
            if not held and not work.done():
                lost.set()
                work.cancel()
                return


_worker: SyncWorker | None = None


def worker_enabled() -> bool:
    return os.getenv("SYNC_WORKER_ENABLED", "true").lower() not in {"0", "false", "no"}


def worker_slots() -> int:
    try:
        return max(int(os.getenv("SYNC_WORKER_SLOTS", "2")), 1)
    except ValueError:
        return 2


def start_worker(handler: Handler) -> None:
    global _worker
    if worker_enabled():
        _worker = SyncWorker(handler, worker_slots())
        _worker.start()


async def stop_worker() -> None:
    global _worker
    if _worker is not None:
        await _worker.stop()
        _worker = None


def notify_worker() -> None:
    """Start on a new job now rather than at the next poll. Other processes will still poll."""
    if _worker is not None:
        _worker.notify()


async def _main() -> None:
    from .adaptive_api import process_sync_job
    from .db import init_db
    from .monitoring import configure_logging

    configure_logging()
    init_db()
    worker = SyncWorker(process_sync_job, worker_slots())
    worker.start()
    await asyncio.gather(*worker._tasks)


if __name__ == "__main__":
    asyncio.run(_main())
