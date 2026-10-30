"""Durable sync queue columns, and a per-feature counter in coach_usage.

Jobs still active at this point lost their worker, or belong to an instance on its way out, and
never recorded how many games they wanted, so they are failed rather than resumed.

Revision ID: a4d9e2f7c613
Revises: e7b3c9a1d5f4
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a4d9e2f7c613"
down_revision: str | None = "e7b3c9a1d5f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_sqlite() -> bool:
    return op.get_context().dialect.name == "sqlite"


def _rebuild_sqlite_coach_usage(*key: str) -> None:
    """SQLite can't change a primary key, so copy the rows into a table with the new one."""
    op.rename_table("coach_usage", "coach_usage_old")
    columns = [
        sa.Column("subject", sa.String(length=64), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("questions", sa.Integer(), nullable=False),
    ]
    if "feature" in key:
        columns.append(
            sa.Column("feature", sa.String(length=20), nullable=False, server_default="coach")
        )
    op.create_table("coach_usage", *columns, sa.PrimaryKeyConstraint(*key))
    op.execute(
        "INSERT INTO coach_usage (subject, day, questions) "
        "SELECT subject, day, questions FROM coach_usage_old"
    )
    op.drop_table("coach_usage_old")


def upgrade() -> None:
    if _is_sqlite():
        _rebuild_sqlite_coach_usage("subject", "day", "feature")
    else:
        op.add_column(
            "coach_usage",
            sa.Column("feature", sa.String(length=20), nullable=False, server_default="coach"),
        )
        op.drop_constraint("coach_usage_pkey", "coach_usage", type_="primary")
        op.create_primary_key("coach_usage_pkey", "coach_usage", ["subject", "day", "feature"])

    op.add_column(
        "sync_jobs",
        sa.Column("max_games", sa.Integer(), nullable=False, server_default="2000"),
    )
    op.add_column("sync_jobs", sa.Column("worker_id", sa.String(length=100), nullable=True))
    op.add_column(
        "sync_jobs",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "sync_jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        "UPDATE sync_jobs SET status = 'failed', "
        "error = 'Sync was interrupted before it finished. Start it again to resume.' "
        "WHERE status IN ('queued', 'fetching', 'analyzing')"
    )


def downgrade() -> None:
    op.drop_column("sync_jobs", "heartbeat_at")
    op.drop_column("sync_jobs", "attempts")
    op.drop_column("sync_jobs", "worker_id")
    op.drop_column("sync_jobs", "max_games")

    op.execute("DELETE FROM coach_usage WHERE feature <> 'coach'")
    if _is_sqlite():
        _rebuild_sqlite_coach_usage("subject", "day")
    else:
        op.drop_constraint("coach_usage_pkey", "coach_usage", type_="primary")
        op.drop_column("coach_usage", "feature")
        op.create_primary_key("coach_usage_pkey", "coach_usage", ["subject", "day"])
