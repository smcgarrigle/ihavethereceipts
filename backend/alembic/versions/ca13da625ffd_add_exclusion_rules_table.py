"""add_exclusion_rules_table

Revision ID: ca13da625ffd
Revises: e16c61053750
Create Date: 2026-05-28

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ca13da625ffd"
down_revision: str | Sequence[str] | None = "e16c61053750"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Seed data: current hardcoded exclusion values migrated to the DB.
_ANALYTICS_SEEDS = [
    ("analytics", "excluded", "Hidden from Dashboard spending charts"),
    ("analytics", "other", "Hidden from Dashboard spending charts"),
    ("analytics", "taxes & fees", "Non-grocery cost"),
    ("analytics", "crv (tax)", "Non-grocery cost"),
]

_PREDICTION_SEEDS = [
    ("predictions", "Excluded", "Hidden from Restock cadence engine"),
    ("predictions", "Other", "Hidden from Restock cadence engine"),
    ("predictions", "Non-Alcoholic Beer", "Excluded from purchase predictions"),
    ("predictions", "Fees & Taxes", "Non-grocery cost"),
    ("predictions", "CRV (tax)", "Non-grocery cost"),
]


def upgrade() -> None:
    """Create exclusion_rules table and seed with current hardcoded values."""
    conn = op.get_bind()

    # Only create if not already present (idempotent)
    inspector = sa.inspect(conn)
    if "exclusion_rules" not in inspector.get_table_names():
        op.create_table(
            "exclusion_rules",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            # index created explicitly below — index=True here would create
            # ix_exclusion_rules_scope twice and break fresh installs
            sa.Column("scope", sa.String, nullable=False),
            sa.Column("pattern", sa.String, nullable=False),
            sa.Column("reason", sa.String, nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.create_index("ix_exclusion_rules_id", "exclusion_rules", ["id"])
        op.create_index("ix_exclusion_rules_scope", "exclusion_rules", ["scope"])

    # Seed rows (skip if already present)
    rules_table = sa.table(
        "exclusion_rules",
        sa.column("scope", sa.String),
        sa.column("pattern", sa.String),
        sa.column("reason", sa.String),
    )
    existing = {
        (row[0], row[1])
        for row in conn.execute(sa.text("SELECT scope, pattern FROM exclusion_rules")).fetchall()
    }
    seeds = _ANALYTICS_SEEDS + _PREDICTION_SEEDS
    to_insert = [
        {"scope": s, "pattern": p, "reason": r} for s, p, r in seeds if (s, p) not in existing
    ]
    if to_insert:
        op.bulk_insert(rules_table, to_insert)


def downgrade() -> None:
    """Drop exclusion_rules table."""
    op.drop_table("exclusion_rules")
