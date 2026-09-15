"""Which corrections went into which OCR prompt, and when."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CorrectionUsage(Base):
    """One correction included in one OCR call's prompt.

    ``content_key`` is the durable reference. ``correction_id`` is kept for
    convenience only and deliberately has no foreign key: re-saving a review
    deletes and re-creates that receipt's correction rows, so the id a usage
    row recorded can disappear while the same lesson lives on under a new id.
    """

    __tablename__ = "correction_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_key: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    correction_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    receipt_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("receipts.id"), nullable=False, index=True
    )
    used_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False, index=True
    )
