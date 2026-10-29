"""opening repertoire builder and drill

Revision ID: c3e8a1f5d7b2
Revises: b7d41f3a9c20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c3e8a1f5d7b2"
down_revision: str | None = "b7d41f3a9c20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "repertoires",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column(
            "player_id",
            sa.String(length=32),
            sa.ForeignKey("players.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("color", sa.String(length=5), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_repertoires_player_id"), "repertoires", ["player_id"])
    op.create_table(
        "repertoire_moves",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column(
            "repertoire_id",
            sa.String(length=32),
            sa.ForeignKey("repertoires.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parent_fen_epd", sa.String(length=100), nullable=False),
        sa.Column("san", sa.String(length=12), nullable=False),
        sa.Column("uci", sa.String(length=5), nullable=False),
        sa.Column("fen_after", sa.String(length=100), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("mistake_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("repertoire_id", "parent_fen_epd", "uci"),
    )
    op.create_index(
        op.f("ix_repertoire_moves_repertoire_id"), "repertoire_moves", ["repertoire_id"]
    )
    op.create_index(
        op.f("ix_repertoire_moves_parent_fen_epd"), "repertoire_moves", ["parent_fen_epd"]
    )
    op.create_table(
        "repertoire_reviews",
        sa.Column(
            "move_id",
            sa.String(length=32),
            sa.ForeignKey("repertoire_moves.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_days", sa.Integer(), nullable=False),
        sa.Column("ease", sa.Float(), nullable=False),
        sa.Column("streak", sa.Integer(), nullable=False),
        sa.Column("last_result", sa.String(length=10), nullable=True),
    )
    op.create_index(op.f("ix_repertoire_reviews_due_at"), "repertoire_reviews", ["due_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_repertoire_reviews_due_at"), table_name="repertoire_reviews")
    op.drop_table("repertoire_reviews")
    op.drop_index(op.f("ix_repertoire_moves_parent_fen_epd"), table_name="repertoire_moves")
    op.drop_index(op.f("ix_repertoire_moves_repertoire_id"), table_name="repertoire_moves")
    op.drop_table("repertoire_moves")
    op.drop_index(op.f("ix_repertoires_player_id"), table_name="repertoires")
    op.drop_table("repertoires")
