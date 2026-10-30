"""users, sign-in identities, player ownership and daily coach usage

Revision ID: f2a6c8e1b3d7
Revises: d4f7b9e2c1a8
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f2a6c8e1b3d7"
down_revision: str | None = "d4f7b9e2c1a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("plan", sa.String(length=20), nullable=False, server_default="free"),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("plan IN ('free', 'paid')", name="ck_users_plan"),
    )
    op.create_table(
        "auth_identities",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "subject"),
    )
    op.create_index(op.f("ix_auth_identities_user_id"), "auth_identities", ["user_id"])
    op.create_table(
        "user_players",
        sa.Column(
            "player_id",
            sa.String(length=32),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.String(length=32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("verified_by", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_user_players_user_id"), "user_players", ["user_id"])
    op.create_table(
        "coach_usage",
        sa.Column("subject", sa.String(length=64), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("questions", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("coach_usage")
    op.drop_index(op.f("ix_user_players_user_id"), table_name="user_players")
    op.drop_table("user_players")
    op.drop_index(op.f("ix_auth_identities_user_id"), table_name="auth_identities")
    op.drop_table("auth_identities")
    op.drop_table("users")
