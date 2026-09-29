from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MergeLog(Base):
    __tablename__ = "merge_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    target_item_id: Mapped[int] = mapped_column(Integer, ForeignKey("items.id"), nullable=False)
    source_item_name: Mapped[str] = mapped_column(String, nullable=False)
    source_item_category_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    receipt_item_ids: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list of IDs moved
    # JSON list of store_item_aliases ids moved to the target; null on logs
    # written before store names existed
    alias_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    merged_at: Mapped[datetime | None] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
