"""add ocr_data to receipts

Revision ID: b35eef237250
Revises: 7486acea3617
Create Date: 2025-12-26 15:28:40.370984

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b35eef237250"
down_revision: str | Sequence[str] | None = "7486acea3617"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade():
    op.add_column("receipts", sa.Column("ocr_data", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("receipts", "ocr_data")
