"""add_nutrients_to_item

Revision ID: e16c61053750
Revises: 12d2ac6e4a53
Create Date: 2026-05-15 00:19:52.310536

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e16c61053750"
down_revision: str | Sequence[str] | None = "12d2ac6e4a53"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    cols = [c["name"] for c in sa.inspect(conn).get_columns("items")]
    if "nutrients" not in cols:
        op.add_column("items", sa.Column("nutrients", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("items", "nutrients")
