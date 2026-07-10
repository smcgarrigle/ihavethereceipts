from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Receipt(Base):
    __tablename__ = "receipts"

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"))
    image_path = Column(String)
    total_amount = Column(Float)
    purchase_date = Column(DateTime)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Discount fields
    discount_amount = Column(Float, nullable=True)
    discount_type = Column(String, nullable=True)
    discount_description = Column(String, nullable=True)

    # Notes field
    notes = Column(Text, nullable=True)

    # Status field
    status = Column(String, default="pending")  # pending, processing, completed, failed
    error_message = Column(Text, nullable=True)

    # OCR data storage (JSON string)
    ocr_data = Column(Text, nullable=True)

    # Order Number (Extracted from digital PDFs)
    order_number = Column(String, unique=True, nullable=True)

    # Relationships
    store = relationship("Store", back_populates="receipts")
    items = relationship("ReceiptItem", back_populates="receipt", cascade="all, delete-orphan")


class ReceiptItem(Base):
    __tablename__ = "receipt_items"

    id = Column(Integer, primary_key=True, index=True)
    receipt_id = Column(Integer, ForeignKey("receipts.id"))
    item_id = Column(Integer, ForeignKey("items.id"))
    quantity = Column(Float, default=1.0)
    price = Column(Float)

    # Notes can store discount/fee breakdown as JSON
    notes = Column(Text, nullable=True)

    # Unit pricing fields
    unit_price = Column(Float, nullable=True)  # The effective unit price paid
    unit_type = Column(String, nullable=True)
    weight = Column(Float, nullable=True)

    # Pricing Breakdown (New)
    original_unit_price = Column(Float, nullable=True)  # Price before discount
    total_discount = Column(Float, nullable=True)  # Total savings for this line item

    # Relationships
    receipt = relationship("Receipt", back_populates="items")
    item = relationship("Item")
