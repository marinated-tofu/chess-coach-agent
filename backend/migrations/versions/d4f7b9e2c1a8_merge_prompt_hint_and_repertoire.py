"""merge the prompt/hint branch with the puzzle and repertoire branch

Revision ID: d4f7b9e2c1a8
Revises: a1b2c3d4e5f6, c3e8a1f5d7b2
"""

from collections.abc import Sequence

revision: str = "d4f7b9e2c1a8"
down_revision: tuple[str, str] = ("a1b2c3d4e5f6", "c3e8a1f5d7b2")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
