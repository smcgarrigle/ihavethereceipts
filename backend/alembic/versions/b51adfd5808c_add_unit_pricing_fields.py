"""Add unit pricing fields

Revision ID: b51adfd5808c
Revises: 1b992fdb4982
Create Date: 2025-12-15 16:27:44.504625

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b51adfd5808c"
down_revision: str | Sequence[str] | None = "1b992fdb4982"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add unit pricing fields to receipt_items
    op.add_column("receipt_items", sa.Column("unit_price", sa.Float(), nullable=True))
    op.add_column(
        "receipt_items", sa.Column("unit_type", sa.String(), nullable=True)
    )  # 'lb', 'oz', 'kg', 'each'
    op.add_column("receipt_items", sa.Column("weight", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("receipt_items", "unit_price")
    op.drop_column("receipt_items", "unit_type")
    op.drop_column("receipt_items", "weight")
