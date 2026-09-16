"""SQLAlchemy model for OCR corrections captured from the human review sandbox."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OcrCorrection(Base):
    """A single human fix to an AI extraction, kept as few-shot training signal.

    field: 'name' | 'price' | 'quantity' | 'store_name' | 'total_amount'
           | 'item_missed' (human added a line the AI skipped)
           | 'item_hallucinated' (AI produced a line the human deleted)
    """

    __tablename__ = "ocr_corrections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("receipts.id"), nullable=False, index=True
    )
    store_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("stores.id"), nullable=True, index=True
    )
    field: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # 'image' | 'pdf' | 'paste' — how the receipt came in. Nullable only so rows
    # written before the column existed can be backfilled by the migration.
    input_type: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # Durable identity of the lesson (app.services.correction_keys.content_key).
    # Rows are re-created on every re-save; this key is not.
    content_key: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    item_context: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # item name, for field-level fixes
    # How many of the item the line held, for price and quantity fixes. Null on
    # rows written before the column existed; there is no way to recover it.
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
