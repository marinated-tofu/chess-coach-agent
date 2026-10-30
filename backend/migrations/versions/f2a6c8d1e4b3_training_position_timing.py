"""training positions carry time trainer data

Revision ID: f2a6c8d1e4b3
Revises: d4f7b9e2c1a8
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f2a6c8d1e4b3"
down_revision: str | None = "d4f7b9e2c1a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("training_positions") as batch:
        batch.add_column(sa.Column("timing", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("training_positions") as batch:
        batch.drop_column("timing")
