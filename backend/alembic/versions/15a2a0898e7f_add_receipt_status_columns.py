"""add_receipt_status_columns

Revision ID: 15a2a0898e7f
Revises: b35eef237250
Create Date: 2026-02-14 17:18:07.234322

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "15a2a0898e7f"
down_revision: str | Sequence[str] | None = "b35eef237250"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "receipts", sa.Column("status", sa.String(), server_default="completed", nullable=False)
    )
    op.add_column("receipts", sa.Column("error_message", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("receipts", "error_message")
    op.drop_column("receipts", "status")
