"""Daily limit on coach questions, counted on the server per user or per anonymous address.

Anonymous visitors have a limit too, otherwise signing out would be a way around it.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from fastapi import HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .auth import session_secret
from .db_models import CoachUsageRow, UserRow

DEFAULT_LIMITS = {"anonymous": 5, "free": 20, "paid": 200}
LIMIT_ENV = {
    "anonymous": "COACH_DAILY_LIMIT_ANONYMOUS",
    "free": "COACH_DAILY_LIMIT_FREE",
    "paid": "COACH_DAILY_LIMIT_PAID",
}


class CoachQuota(BaseModel):
    limit: int
    used: int
    remaining: int
    resets_at: datetime


def daily_limit(plan: str) -> int:
    try:
        return max(int(os.environ[LIMIT_ENV[plan]]), 0)
    except (KeyError, ValueError):
        return DEFAULT_LIMITS[plan]


@dataclass(frozen=True)
class QuotaScope:
    subject: str
    plan: str  # "anonymous", "free" or "paid"

    @property
    def limit(self) -> int:
        return daily_limit(self.plan)


def _today() -> date:
    return datetime.now(UTC).date()


def resets_at() -> datetime:
    return datetime.combine(_today() + timedelta(days=1), time.min, tzinfo=UTC)


def client_address(request: Request) -> str:
    """The caller's address. X-Forwarded-For is client-supplied except for the entries our own
    proxies append, so only the last TRUSTED_PROXY_HOPS entries count."""
    try:
        hops = max(int(os.getenv("TRUSTED_PROXY_HOPS", "0")), 0)
    except ValueError:
        hops = 0
    forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",")]
    forwarded = [part for part in forwarded if part]
    if hops and len(forwarded) >= hops:
        return forwarded[-hops]
    return request.client.host if request.client else "unknown"


def quota_scope(session: Session, request: Request, user_id: str | None) -> QuotaScope:
    user = session.get(UserRow, user_id) if user_id else None
    if user is not None:
        return QuotaScope(f"user:{user.id}", user.plan)
    # Keyed, so the table never holds a usable IP address.
    digest = hmac.new(session_secret(), client_address(request).encode(), hashlib.sha256)
    return QuotaScope(f"anon:{digest.hexdigest()[:40]}", "anonymous")


def coach_quota(session: Session, scope: QuotaScope) -> CoachQuota:
    row = session.get(CoachUsageRow, (scope.subject, _today()))
    used = row.questions if row else 0
    return CoachQuota(
        limit=scope.limit,
        used=used,
        remaining=max(scope.limit - used, 0),
        resets_at=resets_at(),
    )


def take_question(session: Session, scope: QuotaScope) -> bool:
    """Count one question, or return False at the limit. The increment and the limit check are
    a single UPDATE, so parallel requests cannot slip past it."""
    insert = postgresql_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    day = _today()
    session.execute(
        insert(CoachUsageRow)
        .values(subject=scope.subject, day=day, questions=0)
        .on_conflict_do_nothing()
    )
    taken = session.execute(
        update(CoachUsageRow)
        .where(
            CoachUsageRow.subject == scope.subject,
            CoachUsageRow.day == day,
            CoachUsageRow.questions < scope.limit,
        )
        .values(questions=CoachUsageRow.questions + 1)
    )
    return taken.rowcount == 1


def give_back_question(session: Session, scope: QuotaScope) -> None:
    """Undo a counted question that never got an answer."""
    session.execute(
        update(CoachUsageRow)
        .where(
            CoachUsageRow.subject == scope.subject,
            CoachUsageRow.day == _today(),
            CoachUsageRow.questions > 0,
        )
        .values(questions=CoachUsageRow.questions - 1)
    )


def limit_reached(scope: QuotaScope) -> HTTPException:
    limit = scope.limit
    questions = f"{limit} coach {'question' if limit == 1 else 'questions'}"
    if scope.plan == "anonymous":
        message = f"You've used your {questions} for today. Sign in with Lichess to ask more."
    else:
        message = f"You've used your {questions} for today. Your limit resets at midnight UTC."
    retry_after = int((resets_at() - datetime.now(UTC)).total_seconds()) + 1
    return HTTPException(429, message, headers={"Retry-After": str(retry_after)})
