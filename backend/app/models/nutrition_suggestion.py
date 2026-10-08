from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.item import Item


class NutritionSuggestion(Base):
    __tablename__ = "nutrition_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(Integer, ForeignKey("items.id"), index=True)
    fdc_id: Mapped[int] = mapped_column(Integer)
    fdc_description: Mapped[str] = mapped_column(String)
    fdc_brand: Mapped[str | None] = mapped_column(String, nullable=True)
    match_score: Mapped[float] = mapped_column(Float)
    nutrients: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String, default="pending")
    batch_id: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationship to item
    item: Mapped[Item] = relationship("Item")
