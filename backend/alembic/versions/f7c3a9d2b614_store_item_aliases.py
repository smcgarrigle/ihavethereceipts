"""Permanent per-store names: what each store prints for an item

Revision ID: f7c3a9d2b614
Revises: e8b2f5a1c3d4
Create Date: 2026-09-29 20:00:00.000000

The correction block in the prompt holds ten lessons and forgets: a lesson the
model follows is never recorded again, so it slides out as other items are
corrected. This table is the permanent layer. After extraction, a line whose
text this store has printed before is matched to the item it was saved as.

Replayed on the live corpus in upload order, with the table built only from
earlier receipts: exact text found an item for 47.8% of lines and was right
95.2% of the time; fuzzy matching added hits but more wrong ones; latest save
beat majority vote. Together with name matching, right-item matches rose from
84.8% to 90.6%.

Created empty. ``scripts/backfill_store_names.py`` fills it from past receipts.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7c3a9d2b614"
down_revision: str | Sequence[str] | None = "e8b2f5a1c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "store_item_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("text_key", sa.String(), nullable=False),
        sa.Column("printed_text", sa.Text(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("store_id", "text_key", name="uq_store_item_alias"),
    )
    op.create_index(
        op.f("ix_store_item_aliases_item_id"), "store_item_aliases", ["item_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_store_item_aliases_item_id"), table_name="store_item_aliases")
    op.drop_table("store_item_aliases")
