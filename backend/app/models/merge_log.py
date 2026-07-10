from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.database import Base


class MergeLog(Base):
    __tablename__ = "merge_logs"

    id = Column(Integer, primary_key=True, index=True)
    target_item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    source_item_name = Column(String, nullable=False)
    source_item_category_id = Column(Integer, nullable=True)
    receipt_item_ids = Column(Text, nullable=False)  # JSON list of IDs moved
    merged_at = Column(DateTime, default=datetime.utcnow)
