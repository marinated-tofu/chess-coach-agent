"""training positions can come from the puzzle library

Revision ID: b7d41f3a9c20
Revises: 6c2a9df0c41b
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b7d41f3a9c20"
down_revision: str | None = "6c2a9df0c41b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("training_positions") as batch:
        batch.add_column(
            sa.Column("source", sa.String(length=10), nullable=False, server_default="game")
        )
        batch.add_column(sa.Column("puzzle_id", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("rating", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("solution", sa.JSON(), nullable=True))
    op.create_index(
        op.f("ix_training_positions_puzzle_id"), "training_positions", ["puzzle_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_training_positions_puzzle_id"), table_name="training_positions")
    with op.batch_alter_table("training_positions") as batch:
        batch.drop_column("solution")
        batch.drop_column("rating")
        batch.drop_column("puzzle_id")
        batch.drop_column("source")
