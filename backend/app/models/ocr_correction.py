"""SQLAlchemy model for OCR corrections captured from the human review sandbox."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
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
    item_context: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # item name, for field-level fixes
    ai_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
