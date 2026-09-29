"""Permanent per-store names: what each store prints, and the item it means.

The correction block in the prompt holds ten lessons and forgets. A lesson the
model follows is never recorded again, so it slides out of the block as other
items are corrected, and the next receipt comes back with the old text. This is
the layer that does not forget: after extraction, a line whose text this store
has printed before is matched to the item it was last saved as.

It needs no prompt space and no store known in advance: the store is read from
the receipt before items are matched, so it works on a first upload.

Replayed on the live corpus in upload order, with the table built only from
earlier receipts, exact text found an item for 47.8% of lines and was right
95.2% of the time. Fuzzy matching added hits but more wrong ones, and the latest
save beat a majority vote, so lookups are exact and the latest save wins.
"""

import json
import logging
import re
from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.models import Item, StoreItemAlias

logger = logging.getLogger(__name__)

REVIEW_SOURCE = "review"
BACKFILL_SOURCE = "backfill"


def text_key(text: str | None) -> str:
    """Lookup form of printed text: lowercased, whitespace collapsed."""
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def read_text(line: dict) -> str:
    """What the model returned for a line, before any rename to a catalog name."""
    return (line.get("original_ocr_name") or line.get("name") or "").strip()


def item_for(db: Session, store_id: int | None, text: str | None) -> Item | None:
    """The item this store's printed text was last saved as, or None.

    None as well when the item has since been deleted. Never raises: a failed
    lookup leaves name matching to do what it did before.
    """
    key = text_key(text)
    if not store_id or not key:
        return None
    try:
        alias = (
            db.query(StoreItemAlias)
            .filter(StoreItemAlias.store_id == store_id, StoreItemAlias.text_key == key)
            .first()
        )
        return db.get(Item, alias.item_id) if alias else None
    except Exception:
        logger.exception("Store name lookup failed for store %s", store_id)
        return None


def remember_receipt(db: Session, receipt, source: str = REVIEW_SOURCE) -> int:
    """Record each saved line's printed text against the item it was saved as.

    The latest save wins. Returns the number of names written. The caller
    commits. Never raises: the review is already saved.
    """
    if not receipt.store_id or not receipt.ocr_data:
        return 0
    try:
        data = json.loads(receipt.ocr_data)
    except (json.JSONDecodeError, TypeError):
        return 0
    if not isinstance(data, dict) or data.get("produce_mode"):
        return 0
    extracted = data.get("items") or []
    if not extracted:
        return 0

    try:
        from app.models import ReceiptItem
        from app.services.correction_service import pair_receipt_lines
        from app.services.spend import line_total

        # Queried rather than read from receipt.items: the review save adds its
        # lines by receipt_id, so the relationship can still hold the old ones.
        db.flush()
        lines = (
            db.query(ReceiptItem)
            .filter(ReceiptItem.receipt_id == receipt.id, ReceiptItem.item_id.isnot(None))
            .all()
        )
        ids = {line.item_id for line in lines}
        names = {row[0]: row[1] for row in db.query(Item.id, Item.name).filter(Item.id.in_(ids))}
        saved = [
            SimpleNamespace(
                item_id=line.item_id,
                name=names.get(line.item_id) or "",
                final_price=line_total(line),
            )
            for line in lines
        ]
        pairs, _, _ = pair_receipt_lines(extracted, saved)

        latest: dict[str, tuple[str, int]] = {}
        for line, saved_line in pairs:
            text = read_text(line)
            if text_key(text):
                latest[text_key(text)] = (text, saved_line.item_id)
        if not latest:
            return 0

        existing = {
            alias.text_key: alias
            for alias in db.query(StoreItemAlias).filter(
                StoreItemAlias.store_id == receipt.store_id,
                StoreItemAlias.text_key.in_(latest),
            )
        }
        now = datetime.now(UTC)
        for key, (text, item_id) in latest.items():
            alias = existing.get(key)
            if alias is None:
                db.add(
                    StoreItemAlias(
                        store_id=receipt.store_id,
                        text_key=key,
                        printed_text=text,
                        item_id=item_id,
                        source=source,
                    )
                )
            else:
                alias.item_id = item_id
                alias.printed_text = text
                alias.source = source
                alias.updated_at = now
        db.flush()
        return len(latest)
    except Exception:
        logger.exception("Failed to remember store names for receipt %s", receipt.id)
        return 0


def repoint(db: Session, from_item_id: int, to_item_id: int) -> list[int]:
    """Move names from a merged-away item to the item it was merged into.

    Returns the ids moved, so an undo can move exactly those back.
    """
    moved = db.query(StoreItemAlias).filter(StoreItemAlias.item_id == from_item_id).all()
    for alias in moved:
        alias.item_id = to_item_id
    return [alias.id for alias in moved]


def restore(db: Session, alias_ids: list[int], from_item_id: int, to_item_id: int) -> int:
    """Undo ``repoint``: move names back unless a later save has moved them since."""
    if not alias_ids:
        return 0
    back = (
        db.query(StoreItemAlias)
        .filter(StoreItemAlias.id.in_(alias_ids), StoreItemAlias.item_id == from_item_id)
        .all()
    )
    for alias in back:
        alias.item_id = to_item_id
    return len(back)
