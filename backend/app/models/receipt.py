from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base

if TYPE_CHECKING:
    from app.models.item import Item
    from app.models.store import Store


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    store_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("stores.id"))
    image_path: Mapped[str | None] = mapped_column(String)
    total_amount: Mapped[float | None] = mapped_column(Float)
    purchase_date: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Discount fields
    discount_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    discount_type: Mapped[str | None] = mapped_column(String, nullable=True)
    discount_description: Mapped[str | None] = mapped_column(String, nullable=True)

    # Notes field
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Status field
    status: Mapped[str | None] = mapped_column(
        String, default="pending"
    )  # pending, processing, completed, failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # OCR data storage (JSON string)
    ocr_data: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Order Number (Extracted from digital PDFs)
    order_number: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)

    # Relationships
    store: Mapped[Store] = relationship("Store", back_populates="receipts")
    items: Mapped[list[ReceiptItem]] = relationship(
        "ReceiptItem", back_populates="receipt", cascade="all, delete-orphan"
    )


class ReceiptItem(Base):
    __tablename__ = "receipt_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    receipt_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("receipts.id"))
    item_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("items.id"))
    quantity: Mapped[float | None] = mapped_column(Float, default=1.0)
    price: Mapped[float | None] = mapped_column(Float)

    # Notes can store discount/fee breakdown as JSON
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Unit pricing fields
    unit_price: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # The effective unit price paid
    unit_type: Mapped[str | None] = mapped_column(String, nullable=True)
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Pricing Breakdown (New)
    original_unit_price: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # Price before discount
    total_discount: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # Total savings for this line item

    # Relationships
    receipt: Mapped[Receipt] = relationship("Receipt", back_populates="items")
    item: Mapped[Item] = relationship("Item")
