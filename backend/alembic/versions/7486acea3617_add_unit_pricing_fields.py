"""Add unit pricing fields

Revision ID: 7486acea3617
Revises: b51adfd5808c
Create Date: 2025-12-22 10:17:08.350705

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "7486acea3617"
down_revision: str | Sequence[str] | None = "b51adfd5808c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
