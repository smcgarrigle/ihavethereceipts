"""SQLAlchemy model for exclusion rules (analytics + prediction category exclusions)."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ExclusionRule(Base):
    """A category name excluded from analytics and/or prediction engine.

    scope: 'analytics'   — hides the category from dashboard charts and totals.
           'predictions' — hides the category from the restock/cadence engine.
    """

    __tablename__ = "exclusion_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    scope: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )  # 'analytics' | 'predictions'
    pattern: Mapped[str] = mapped_column(String, nullable=False)  # category name substring to match
    reason: Mapped[str | None] = mapped_column(String, nullable=True)  # optional user-facing note
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)
