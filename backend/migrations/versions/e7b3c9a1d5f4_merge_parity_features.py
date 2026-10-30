"""Merge the stats, time trainer, accounts and study plan migrations.

Revision ID: e7b3c9a1d5f4
Revises: f1c6e2d8a4b3, f2a6c8d1e4b3, f2a6c8e1b3d7, f2a9c4d81e36
"""

from typing import Sequence, Union

revision: str = "e7b3c9a1d5f4"
down_revision: Union[str, Sequence[str], None] = (
    "f1c6e2d8a4b3",
    "f2a6c8d1e4b3",
    "f2a6c8e1b3d7",
    "f2a9c4d81e36",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
