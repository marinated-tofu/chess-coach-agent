"""add training position prompt and hint

Revision ID: a1b2c3d4e5f6
Revises: 6c2a9df0c41b
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "6c2a9df0c41b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Databases first created by an older create_all already have these columns.
    existing = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("training_positions")
    }
    if "prompt" not in existing:
        op.add_column(
            "training_positions",
            sa.Column(
                "prompt",
                sa.Text(),
                nullable=False,
                server_default="What would you play in this position?",
            ),
        )
    if "hint" not in existing:
        op.add_column("training_positions", sa.Column("hint", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("training_positions", "hint")
    op.drop_column("training_positions", "prompt")
