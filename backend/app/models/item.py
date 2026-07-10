from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


class Item(Base):
    __tablename__ = "items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    normalized_name = Column(String, index=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    fdc_id = Column(Integer, nullable=True)
    gtin = Column(String, nullable=True)
    off_code = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    image_path = Column(String, nullable=True)
    nutriscore = Column(String, nullable=True)
    ingredients = Column(String, nullable=True)
    nutrients = Column(JSON, nullable=True)
    custom_nutrients = Column(JSON, nullable=True)
    nutrition_source = Column(String, default="auto")
    created_at = Column(DateTime, default=datetime.utcnow)

    @property
    def effective_nutrients(self) -> dict:
        """Returns merged custom_nutrients overriding canonical nutrients"""
        base = self.nutrients or {}
        custom = self.custom_nutrients or {}
        merged = base.copy()
        for k, v in custom.items():
            if v is not None and str(v).strip() != "":
                merged[k] = v
        return merged

    # Relationships
    category = relationship("Category", back_populates="items")
    receipt_items = relationship("ReceiptItem", back_populates="item")


class ItemMatchIgnore(Base):
    __tablename__ = "item_match_ignores"

    id = Column(Integer, primary_key=True, index=True)
    item_id_1 = Column(Integer, ForeignKey("items.id"), nullable=False)
    item_id_2 = Column(Integer, ForeignKey("items.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
