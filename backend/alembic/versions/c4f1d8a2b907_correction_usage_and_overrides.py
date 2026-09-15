"""Correction usage log, overrides, and content keys on corrections

Revision ID: c4f1d8a2b907
Revises: a1d4c9e77b02
Create Date: 2026-09-15 12:00:00.000000

Adds what the Corrections page needs:

- ``ocr_corrections.input_type`` and ``content_key``, backfilled for existing rows
- ``correction_usage``: which lessons went into which OCR prompt
- ``correction_overrides``: suppressed and pinned decisions, keyed on content,
  because correction rows are re-created whenever a review is saved again

``_input_type_of`` and ``_content_key`` are frozen copies of
``app.services.correction_service.input_type_of`` and
``app.services.correction_keys.content_key``. Migrations must not import
application code, which can change after this revision is written;
``tests/test_correction_keys_and_overrides.py`` asserts the copies agree.
"""

import hashlib
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4f1d8a2b907"
down_revision: str | Sequence[str] | None = "a1d4c9e77b02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _input_type_of(image_path):
    if not image_path:
        return "paste"
    return "pdf" if image_path.lower().endswith(".pdf") else "image"


def _content_key(store_id, input_type, field, ai_value, approved_value):
    parts = [
        "" if store_id is None else str(store_id),
        input_type,
        field,
        (ai_value or "").strip(),
        (approved_value or "").strip(),
    ]
    return hashlib.sha1("\x1f".join(parts).encode("utf-8"), usedforsecurity=False).hexdigest()


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("ocr_corrections", schema=None) as batch_op:
        batch_op.add_column(sa.Column("input_type", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("content_key", sa.String(length=40), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_ocr_corrections_input_type"), ["input_type"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_ocr_corrections_content_key"), ["content_key"], unique=False
        )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT c.id, c.store_id, c.field, c.ai_value, c.approved_value, r.image_path "
            "FROM ocr_corrections c LEFT JOIN receipts r ON r.id = c.receipt_id"
        )
    ).fetchall()
    updates = []
    for cid, store_id, field, ai_value, approved_value, image_path in rows:
        kind = _input_type_of(image_path)
        updates.append(
            {
                "id": cid,
                "input_type": kind,
                "content_key": _content_key(store_id, kind, field, ai_value, approved_value),
            }
        )
    if updates:
        bind.execute(
            sa.text(
                "UPDATE ocr_corrections SET input_type = :input_type, "
                "content_key = :content_key WHERE id = :id"
            ),
            updates,
        )

    op.create_table(
        "correction_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("content_key", sa.String(length=40), nullable=False),
        sa.Column("correction_id", sa.Integer(), nullable=True),
        sa.Column("receipt_id", sa.Integer(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["receipt_id"], ["receipts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_correction_usage_content_key"), "correction_usage", ["content_key"], unique=False
    )
    op.create_index(
        op.f("ix_correction_usage_receipt_id"), "correction_usage", ["receipt_id"], unique=False
    )
    op.create_index(
        op.f("ix_correction_usage_used_at"), "correction_usage", ["used_at"], unique=False
    )

    op.create_table(
        "correction_overrides",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("content_key", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=True),
        sa.Column("input_type", sa.String(), nullable=False),
        sa.Column("field", sa.String(), nullable=False),
        sa.Column("ai_value", sa.Text(), nullable=True),
        sa.Column("approved_value", sa.Text(), nullable=True),
        sa.Column("suppressed", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("pinned", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_correction_overrides_content_key"),
        "correction_overrides",
        ["content_key"],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_correction_overrides_content_key"), table_name="correction_overrides")
    op.drop_table("correction_overrides")

    op.drop_index(op.f("ix_correction_usage_used_at"), table_name="correction_usage")
    op.drop_index(op.f("ix_correction_usage_receipt_id"), table_name="correction_usage")
    op.drop_index(op.f("ix_correction_usage_content_key"), table_name="correction_usage")
    op.drop_table("correction_usage")

    with op.batch_alter_table("ocr_corrections", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_ocr_corrections_content_key"))
        batch_op.drop_index(batch_op.f("ix_ocr_corrections_input_type"))
        batch_op.drop_column("content_key")
        batch_op.drop_column("input_type")
