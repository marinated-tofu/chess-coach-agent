"""Daily limits on model-backed features, counted on the server per user or anonymous address.

Anonymous visitors have limits too, otherwise signing out would be a way around them.

Each feature has its own counter and limit: the coach, practice agent, study plan rationale and
board reading cost different amounts and are used at different rates, so a day of practice should
not use up the coach. A feature takes a `QuotaCharge` right before calling the model and hands it
back if no answer came. At the limit the coach and vision return `limit_reached` (a 429); practice
and the study plan carry on without the model.
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
from .db import session_scope
from .db_models import CoachUsageRow, UserRow

DEFAULT_LIMITS = {
    "coach": {"anonymous": 5, "free": 20, "paid": 200},
    # One session can make several model requests, so it allows fewer uses than a question.
    "practice": {"anonymous": 3, "free": 10, "paid": 100},
    # A plan is weekly; these only leave room for retries when the note failed.
    "study_plan": {"anonymous": 2, "free": 5, "paid": 20},
    "vision": {"anonymous": 3, "free": 10, "paid": 100},
}
LIMIT_ENV = {
    (feature, plan): f"{feature.upper()}_DAILY_LIMIT_{plan.upper()}"
    for feature, limits in DEFAULT_LIMITS.items()
    for plan in limits
}
# What the limit message calls one use of a feature: singular, plural.
USE_NAMES = {
    "coach": ("coach question", "coach questions"),
    "practice": ("practice session", "practice sessions"),
    "study_plan": ("study plan note", "study plan notes"),
    "vision": ("board image read", "board image reads"),
}


class CoachQuota(BaseModel):
    limit: int
    used: int
    remaining: int
    resets_at: datetime


def daily_limit(plan: str, feature: str = "coach") -> int:
    try:
        return max(int(os.environ[LIMIT_ENV[feature, plan]]), 0)
    except (KeyError, ValueError):
        return DEFAULT_LIMITS[feature][plan]


@dataclass(frozen=True)
class QuotaScope:
    subject: str
    plan: str  # "anonymous", "free" or "paid"
    feature: str = "coach"

    @property
    def limit(self) -> int:
        return daily_limit(self.plan, self.feature)


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


def quota_scope(
    session: Session, request: Request, user_id: str | None, feature: str = "coach"
) -> QuotaScope:
    user = session.get(UserRow, user_id) if user_id else None
    if user is not None:
        return QuotaScope(f"user:{user.id}", user.plan, feature)
    # Keyed, so the table never holds a usable IP address.
    digest = hmac.new(session_secret(), client_address(request).encode(), hashlib.sha256)
    return QuotaScope(f"anon:{digest.hexdigest()[:40]}", "anonymous", feature)


def coach_quota(session: Session, scope: QuotaScope) -> CoachQuota:
    row = session.get(CoachUsageRow, (scope.subject, _today(), scope.feature))
    used = row.questions if row else 0
    return CoachQuota(
        limit=scope.limit,
        used=used,
        remaining=max(scope.limit - used, 0),
        resets_at=resets_at(),
    )


def take_quota(session: Session, scope: QuotaScope) -> bool:
    """Count one use, or return False at the limit. The increment and the limit check are
    a single UPDATE, so parallel requests cannot slip past it."""
    insert = postgresql_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    day = _today()
    session.execute(
        insert(CoachUsageRow)
        .values(subject=scope.subject, day=day, feature=scope.feature, questions=0)
        .on_conflict_do_nothing()
    )
    taken = session.execute(
        update(CoachUsageRow)
        .where(
            CoachUsageRow.subject == scope.subject,
            CoachUsageRow.day == day,
            CoachUsageRow.feature == scope.feature,
            CoachUsageRow.questions < scope.limit,
        )
        .values(questions=CoachUsageRow.questions + 1)
    )
    return taken.rowcount == 1


def give_back_quota(session: Session, scope: QuotaScope) -> None:
    """Undo a counted use that never got an answer."""
    session.execute(
        update(CoachUsageRow)
        .where(
            CoachUsageRow.subject == scope.subject,
            CoachUsageRow.day == _today(),
            CoachUsageRow.feature == scope.feature,
            CoachUsageRow.questions > 0,
        )
        .values(questions=CoachUsageRow.questions - 1)
    )


class QuotaCharge:
    """One use of a feature for this request. Blocking, so async routes call it in a thread.

    Each call opens its own short session. With SQLite, a caller must have committed its own
    writes first or this waits on them.
    """

    def __init__(self, request: Request, user_id: str | None, feature: str) -> None:
        self.request = request
        self.user_id = user_id
        self.feature = feature
        self.scope: QuotaScope | None = None
        self.taken = False

    def take(self) -> bool:
        with session_scope() as session:
            self.scope = quota_scope(session, self.request, self.user_id, self.feature)
            self.taken = take_quota(session, self.scope)
        return self.taken

    def refund(self) -> None:
        if not self.taken or self.scope is None:
            return
        self.taken = False
        with session_scope() as session:
            give_back_quota(session, self.scope)


def limit_reached(scope: QuotaScope) -> HTTPException:
    limit = scope.limit
    one, many = USE_NAMES[scope.feature]
    uses = f"{limit} {one if limit == 1 else many}"
    if limit == 0:
        message = (
            f"{many.capitalize()} need an account. Sign in with Lichess to continue."
            if scope.plan == "anonymous"
            else f"{many.capitalize()} aren't available on this plan today."
        )
    elif scope.plan == "anonymous":
        message = f"You've used your {uses} for today. Sign in with Lichess to get more."
    else:
        message = f"You've used your {uses} for today. Your limit resets at midnight UTC."
    retry_after = int((resets_at() - datetime.now(UTC)).total_seconds()) + 1
    return HTTPException(429, message, headers={"Retry-After": str(retry_after)})
