"""Add discount and notes fields

Revision ID: 1b992fdb4982
Revises: e6371d90da65
Create Date: 2025-12-15 10:40:57.342892

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1b992fdb4982"
down_revision: str | Sequence[str] | None = "e6371d90da65"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add discount fields to receipts
    op.add_column(
        "receipts", sa.Column("discount_amount", sa.Float(), nullable=True, server_default="0.0")
    )
    op.add_column("receipts", sa.Column("discount_type", sa.String(), nullable=True))
    op.add_column("receipts", sa.Column("discount_description", sa.String(), nullable=True))
    op.add_column("receipts", sa.Column("notes", sa.Text(), nullable=True))

    # Add notes field to receipt_items
    op.add_column("receipt_items", sa.Column("notes", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("receipts", "discount_amount")
    op.drop_column("receipts", "discount_type")
    op.drop_column("receipts", "discount_description")
    op.drop_column("receipts", "notes")
    op.drop_column("receipt_items", "notes")
