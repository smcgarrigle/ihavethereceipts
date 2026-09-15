"""A person's decision about one lesson: keep it out of prompts, or always include it."""

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CorrectionOverride(Base):
    """Suppressed and pinned state for one lesson.

    Keyed on content rather than on a correction row, because rows are deleted
    and re-created whenever a review is saved again; a decision tied to a row
    id would be lost on the next save. The descriptive columns copy the lesson
    at the time of the decision, so it can still be shown when no correction
    row currently carries that key.
    """

    __tablename__ = "correction_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_key: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    store_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("stores.id"), nullable=True)
    input_type: Mapped[str] = mapped_column(String, nullable=False)
    field: Mapped[str] = mapped_column(String, nullable=False)
    ai_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    suppressed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
