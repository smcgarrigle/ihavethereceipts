"""A person's decision to stop being reminded about an item, for a while or for good."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PredictionDismissal(Base):
    """One item hidden from restock predictions.

    One row per item: dismissing again replaces the earlier decision. ``until``
    is the moment the item may come back, in naive UTC; ``None`` means it stays
    hidden until restored by hand. The decision is about the item, not about a
    store, so it applies wherever the item would have been suggested.
    """

    __tablename__ = "prediction_dismissals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("items.id"), nullable=False, unique=True, index=True
    )
    until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
