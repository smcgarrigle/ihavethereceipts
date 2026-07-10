"""Add manual nutrition override fields

Revision ID: 02b3bc755efd
Revises: ca13da625ffd
Create Date: 2026-06-30 11:35:33.172111

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "02b3bc755efd"
down_revision: str | Sequence[str] | None = "ca13da625ffd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("custom_nutrients", sa.JSON(), nullable=True))
        batch_op.add_column(
            sa.Column("nutrition_source", sa.String(), server_default="auto", nullable=True)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("items", schema=None) as batch_op:
        batch_op.drop_column("nutrition_source")
        batch_op.drop_column("custom_nutrients")

    # ### end Alembic commands ###
