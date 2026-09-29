"""Record where a correction came from, and which item a rename lesson is for

Revision ID: e8b2f5a1c3d4
Revises: d1a7c3b8e520
Create Date: 2026-09-29 12:00:00.000000

Renaming an item in the item editor now records name lessons, not only fixes
made on the review screen.

- ``source``: ``review`` or ``item_editor``. Saving a review deletes and
  re-records that receipt's review lessons; the source column lets it leave
  rename lessons alone. Existing rows are all review lessons, so the server
  default fills them.
- ``item_id``: the item a rename lesson belongs to, so renaming the same item
  again replaces its lessons instead of stacking a second, contradicting set.
  Null for review lessons. No foreign key, for the same reason
  ``correction_usage.correction_id`` has none: the lesson is still true about
  the receipt text if the item is later merged away or deleted.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e8b2f5a1c3d4"
down_revision: str | Sequence[str] | None = "d1a7c3b8e520"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("ocr_corrections", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("source", sa.String(), nullable=False, server_default="review")
        )
        batch_op.add_column(sa.Column("item_id", sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f("ix_ocr_corrections_source"), ["source"], unique=False)
        batch_op.create_index(batch_op.f("ix_ocr_corrections_item_id"), ["item_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("ocr_corrections", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_ocr_corrections_item_id"))
        batch_op.drop_index(batch_op.f("ix_ocr_corrections_source"))
        batch_op.drop_column("item_id")
        batch_op.drop_column("source")
