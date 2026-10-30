"""store each game's UTC start time

Revision ID: f1c6e2d8a4b3
Revises: d4f7b9e2c1a8

The column stays null for existing games: only the date was stored, and the raw PGN headers
were not kept. The next platform sync fills it in without re-analyzing (see adaptive_api.py).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f1c6e2d8a4b3"
down_revision: str | None = "d4f7b9e2c1a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("games") as batch:
        batch.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("games") as batch:
        batch.drop_column("started_at")
