"""Add fdc_override flag to items

Revision ID: a1d4c9e77b02
Revises: f03a57133801
Create Date: 2026-07-20 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1d4c9e77b02"
down_revision: str | Sequence[str] | None = "f03a57133801"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("items", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("fdc_override", sa.Boolean(), server_default=sa.text("0"), nullable=False)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("items", schema=None) as batch_op:
        batch_op.drop_column("fdc_override")
