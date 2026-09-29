"""Record which store names a merge moved, so undo can move them back

Revision ID: a2e6c8f1d905
Revises: f7c3a9d2b614
Create Date: 2026-09-29 20:30:00.000000

A merge deletes the source item and points its store names at the kept item.
Undo recreates the source item under a new id, so it needs the list of names
the merge moved. Null on logs written before this revision: undoing one of
those moves no names, as before.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a2e6c8f1d905"
down_revision: str | Sequence[str] | None = "f7c3a9d2b614"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("merge_logs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("alias_ids", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("merge_logs", schema=None) as batch_op:
        batch_op.drop_column("alias_ids")
