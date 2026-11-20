"""Add prediction_dismissals: items hidden from restock predictions

Revision ID: c4b7e2a9d615
Revises: 9d4e1b7a3c58
Create Date: 2026-11-15 12:00:00.000000

One row per dismissed item. ``until`` is when the item may come back; NULL
means it stays hidden until restored by hand.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4b7e2a9d615"
down_revision: str | Sequence[str] | None = "9d4e1b7a3c58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "prediction_dismissals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("until", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_prediction_dismissals_item_id"),
        "prediction_dismissals",
        ["item_id"],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_prediction_dismissals_item_id"), table_name="prediction_dismissals")
    op.drop_table("prediction_dismissals")
