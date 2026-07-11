"""fix fresh-install schema gaps

Several schema elements were created by the pre-Alembic ``create_all()`` path
and never made it into a migration: ``items.fdc_id``, ``receipts.order_number``
(+ its unique index), and the ``item_match_ignores`` / ``merge_logs`` tables
(the "Add merge logs" revision only altered ``receipts.status``). Legacy
databases already have all of them, so every step below is conditional —
this is a no-op on upgraded installs and completes the schema on fresh ones.

Revision ID: f03a57133801
Revises: f3a91c04d7e2
Create Date: 2026-07-11 00:33:45.366785

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f03a57133801"
down_revision: str | Sequence[str] | None = "f3a91c04d7e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())

    item_cols = {c["name"] for c in insp.get_columns("items")}
    if "fdc_id" not in item_cols:
        with op.batch_alter_table("items", schema=None) as batch_op:
            batch_op.add_column(sa.Column("fdc_id", sa.Integer(), nullable=True))

    receipt_cols = {c["name"] for c in insp.get_columns("receipts")}
    if "order_number" not in receipt_cols:
        with op.batch_alter_table("receipts", schema=None) as batch_op:
            batch_op.add_column(sa.Column("order_number", sa.String(), nullable=True))
        op.create_index(
            "uq_receipts_order_number", "receipts", ["order_number"], unique=True
        )

    if "item_match_ignores" not in tables:
        op.create_table(
            "item_match_ignores",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("item_id_1", sa.Integer(), nullable=False),
            sa.Column("item_id_2", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["item_id_1"], ["items.id"]),
            sa.ForeignKeyConstraint(["item_id_2"], ["items.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if "merge_logs" not in tables:
        op.create_table(
            "merge_logs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("target_item_id", sa.Integer(), nullable=False),
            sa.Column("source_item_name", sa.String(), nullable=False),
            sa.Column("source_item_category_id", sa.Integer(), nullable=True),
            sa.Column("receipt_item_ids", sa.Text(), nullable=False),
            sa.Column("merged_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["target_item_id"], ["items.id"]),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade() -> None:
    """Downgrade schema.

    Intentionally a no-op: on legacy databases this revision changed nothing,
    and removing these elements would destroy data the app depends on.
    """
