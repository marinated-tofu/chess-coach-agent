"""weekly study plans and the activity log that tracks them

Revision ID: f2a9c4d81e36
Revises: d4f7b9e2c1a8
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f2a9c4d81e36"
down_revision: str | None = "d4f7b9e2c1a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "study_plans",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column(
            "player_id",
            sa.String(length=32),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("start_date", sa.String(length=10), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("days", sa.JSON(), nullable=False),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("player_id", "start_date"),
    )
    op.create_index(op.f("ix_study_plans_player_id"), "study_plans", ["player_id"])
    op.create_table(
        "study_activity",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column(
            "player_id",
            sa.String(length=32),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("ref", sa.String(length=64), nullable=False),
        sa.Column("context", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_study_activity_player_id"), "study_activity", ["player_id"])
    op.create_index(op.f("ix_study_activity_created_at"), "study_activity", ["created_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_study_activity_created_at"), table_name="study_activity")
    op.drop_index(op.f("ix_study_activity_player_id"), table_name="study_activity")
    op.drop_table("study_activity")
    op.drop_index(op.f("ix_study_plans_player_id"), table_name="study_plans")
    op.drop_table("study_plans")
