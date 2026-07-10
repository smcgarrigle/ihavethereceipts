"""SQLAlchemy model for OCR corrections captured from the human review sandbox."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.database import Base


class OcrCorrection(Base):
    """A single human fix to an AI extraction, kept as few-shot training signal.

    field: 'name' | 'price' | 'quantity' | 'store_name' | 'total_amount'
           | 'item_missed' (human added a line the AI skipped)
           | 'item_hallucinated' (AI produced a line the human deleted)
    """

    __tablename__ = "ocr_corrections"

    id = Column(Integer, primary_key=True, index=True)
    receipt_id = Column(Integer, ForeignKey("receipts.id"), nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=True, index=True)
    field = Column(String, nullable=False, index=True)
    item_context = Column(Text, nullable=True)  # item name, for field-level fixes
    ai_value = Column(Text, nullable=True)
    approved_value = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
