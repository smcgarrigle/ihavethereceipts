"""What a store prints for an item: the permanent per-store name memory."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StoreItemAlias(Base):
    """One store's printed text for an item, from the last receipt that carried it.

    Keyed on the normalized text the model returned, not on a name: pointing at
    the item means a rename changes the output with no bookkeeping. The latest
    save wins, which replayed better on the live corpus than a majority vote.

    ``item_id`` has no foreign key, for the same reason ``correction_usage`` has
    none on its correction: a merge deletes the source item, and the merge code
    repoints these rows rather than relying on a cascade.
    """

    __tablename__ = "store_item_aliases"
    __table_args__ = (UniqueConstraint("store_id", "text_key", name="uq_store_item_alias"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, ForeignKey("stores.id"), nullable=False)
    # Lowercased, whitespace collapsed: see app.services.store_names.text_key
    text_key: Mapped[str] = mapped_column(String, nullable=False)
    # As the model returned it, for display
    printed_text: Mapped[str] = mapped_column(Text, nullable=False)
    item_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # 'review' (a saved review) | 'backfill' (scripts/backfill_store_names.py)
    source: Mapped[str] = mapped_column(String, nullable=False, default="review")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
