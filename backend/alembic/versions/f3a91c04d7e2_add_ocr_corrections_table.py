"""add ocr_corrections table

Revision ID: f3a91c04d7e2
Revises: 02b3bc755efd
Create Date: 2026-07-06

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a91c04d7e2"
down_revision: str | Sequence[str] | None = "02b3bc755efd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ocr_corrections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "receipt_id", sa.Integer(), sa.ForeignKey("receipts.id"), nullable=False, index=True
        ),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id"), nullable=True, index=True),
        sa.Column("field", sa.String(), nullable=False, index=True),
        sa.Column("item_context", sa.Text(), nullable=True),
        sa.Column("ai_value", sa.Text(), nullable=True),
        sa.Column("approved_value", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ocr_corrections")
