from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.category import Category
    from app.models.receipt import ReceiptItem


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str | None] = mapped_column(String, index=True)
    normalized_name: Mapped[str | None] = mapped_column(String, index=True)
    category_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("categories.id"), nullable=True
    )
    fdc_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gtin: Mapped[str | None] = mapped_column(String, nullable=True)
    off_code: Mapped[str | None] = mapped_column(String, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    image_path: Mapped[str | None] = mapped_column(String, nullable=True)
    nutriscore: Mapped[str | None] = mapped_column(String, nullable=True)
    ingredients: Mapped[str | None] = mapped_column(String, nullable=True)
    nutrients: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    custom_nutrients: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    nutrition_source: Mapped[str | None] = mapped_column(String, default="auto")
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    @property
    def effective_nutrients(self) -> dict[str, Any]:
        """Returns merged custom_nutrients overriding canonical nutrients"""
        base: dict[str, Any] = self.nutrients or {}
        custom: dict[str, Any] = self.custom_nutrients or {}
        merged = base.copy()
        for k, v in custom.items():
            if v is not None and str(v).strip() != "":
                merged[k] = v
        return merged

    # Relationships
    category: Mapped[Category | None] = relationship("Category", back_populates="items")
    receipt_items: Mapped[list[ReceiptItem]] = relationship("ReceiptItem", back_populates="item")


class ItemMatchIgnore(Base):
    __tablename__ = "item_match_ignores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    item_id_1: Mapped[int] = mapped_column(Integer, ForeignKey("items.id"), nullable=False)
    item_id_2: Mapped[int] = mapped_column(Integer, ForeignKey("items.id"), nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
