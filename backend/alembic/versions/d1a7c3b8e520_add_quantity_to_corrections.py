"""Add quantity to corrections

Revision ID: d1a7c3b8e520
Revises: c4f1d8a2b907
Create Date: 2026-09-16 01:00:00.000000

A price correction without the quantity reads as a plain misreading. "4.34 was
corrected to 8.68" is a doubling when the line held two units, and the prompt
had no way to say so. New corrections record the line's quantity; rows written
before this column stay null and are shown as they were.

No backfill: the quantity a line had when its correction was recorded cannot be
recovered, because reviews can be saved again and the line may have changed.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1a7c3b8e520"
down_revision: str | Sequence[str] | None = "c4f1d8a2b907"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("ocr_corrections", schema=None) as batch_op:
        batch_op.add_column(sa.Column("quantity", sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("ocr_corrections", schema=None) as batch_op:
        batch_op.drop_column("quantity")
