"""SQLAlchemy model for exclusion rules (analytics + prediction category exclusions)."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String

from app.database import Base


class ExclusionRule(Base):
    """A category name excluded from analytics and/or prediction engine.

    scope: 'analytics'   — hides the category from dashboard charts and totals.
           'predictions' — hides the category from the restock/cadence engine.
    """

    __tablename__ = "exclusion_rules"

    id = Column(Integer, primary_key=True, index=True)
    scope = Column(String, nullable=False, index=True)  # 'analytics' | 'predictions'
    pattern = Column(String, nullable=False)  # category name substring to match
    reason = Column(String, nullable=True)  # optional user-facing note
    created_at = Column(DateTime, default=datetime.utcnow)
