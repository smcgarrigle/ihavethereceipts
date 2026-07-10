"""Capture human review corrections and feed them back into the OCR prompt.

Every review-sandbox save is compared against the AI's original extraction
(receipt.ocr_data). Meaningful differences are stored as OcrCorrection rows,
and the most recent ones are injected into the receipt prompt as few-shot
guidance — per store when the store is known, global otherwise.
"""

import json
import logging

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from app.models.ocr_correction import OcrCorrection

logger = logging.getLogger(__name__)

# Below this similarity an AI item and a reviewed item are considered
# different products, not a rename of the same line
_PAIR_THRESHOLD = 55
# Above this the names are close enough that storing a correction adds noise
_NOISE_THRESHOLD = 97


def _pair_items(ai_items: list[dict], reviewed_items: list) -> tuple[list, list, list]:
    """Greedy best-match pairing of AI lines to reviewed lines by name similarity.

    Returns (pairs, unmatched_ai, unmatched_reviewed).
    """
    remaining = list(range(len(reviewed_items)))
    pairs = []
    unmatched_ai = []

    for ai in ai_items:
        ai_name = (ai.get("original_ocr_name") or ai.get("name") or "").strip()
        if not ai_name:
            continue
        best_score, best_idx = 0.0, None
        for idx in remaining:
            score = fuzz.token_set_ratio(ai_name.lower(), reviewed_items[idx].name.lower())
            # A matching final price is strong evidence of the same line
            ai_price = ai.get("final_price")
            if ai_price is not None and abs(ai_price - reviewed_items[idx].final_price) < 0.01:
                score += 15
            if score > best_score:
                best_score, best_idx = score, idx
        if best_idx is not None and best_score >= _PAIR_THRESHOLD:
            pairs.append((ai, reviewed_items[best_idx]))
            remaining.remove(best_idx)
        else:
            unmatched_ai.append(ai)

    return pairs, unmatched_ai, [reviewed_items[i] for i in remaining]


def record_corrections(db: Session, receipt, reviewed_items: list) -> int:
    """Diff the AI extraction against the human-approved items and persist fixes.

    Idempotent per receipt: re-saving a review replaces its correction rows.
    Returns the number of corrections recorded. Never raises — the save flow
    must not fail because of feedback bookkeeping.
    """
    try:
        ocr_data = json.loads(receipt.ocr_data) if receipt.ocr_data else {}
    except (json.JSONDecodeError, TypeError):
        return 0

    ai_items = ocr_data.get("items") or []
    # Manual/produce receipts have no AI extraction to learn from
    if not ai_items or ocr_data.get("produce_mode"):
        return 0

    try:
        db.query(OcrCorrection).filter(OcrCorrection.receipt_id == receipt.id).delete()

        corrections: list[OcrCorrection] = []

        def add(field, ai_value, approved_value, item_context=None):
            corrections.append(
                OcrCorrection(
                    receipt_id=receipt.id,
                    store_id=receipt.store_id,
                    field=field,
                    item_context=item_context,
                    ai_value=str(ai_value) if ai_value is not None else None,
                    approved_value=str(approved_value) if approved_value is not None else None,
                )
            )

        pairs, unmatched_ai, unmatched_reviewed = _pair_items(ai_items, reviewed_items)

        for ai, human in pairs:
            ai_name = (ai.get("original_ocr_name") or ai.get("name") or "").strip()
            similarity = fuzz.ratio(ai_name.lower(), human.name.lower())
            if ai_name and similarity < _NOISE_THRESHOLD:
                add("name", ai_name, human.name)

            ai_price = ai.get("final_price")
            if ai_price is not None and abs(ai_price - human.final_price) >= 0.01:
                add("price", f"{ai_price:.2f}", f"{human.final_price:.2f}", human.name)

            ai_qty = ai.get("quantity")
            if ai_qty is not None and human.quantity and abs(ai_qty - human.quantity) >= 0.01:
                add("quantity", ai_qty, human.quantity, human.name)

        for ai in unmatched_ai:
            ai_name = (ai.get("original_ocr_name") or ai.get("name") or "").strip()
            if ai_name:
                add("item_hallucinated", ai_name, None)

        for human in unmatched_reviewed:
            add("item_missed", None, human.name)

        db.add_all(corrections)
        # Caller's commit persists these together with the reviewed items
        return len(corrections)
    except Exception:
        logger.exception(f"Failed to record OCR corrections for receipt {receipt.id}")
        return 0


def get_correction_prompt(db: Session, store_name: str | None = None, limit: int = 10) -> str:
    """Build a few-shot prompt block from recent corrections, or "" when none.

    Prefers corrections from the given store; falls back to the most recent
    corrections across all stores so first-pass OCR (store unknown) still
    benefits from global patterns.
    """
    try:
        from app.models import Store

        query = db.query(OcrCorrection).order_by(OcrCorrection.created_at.desc())
        scope = "all stores"
        if store_name:
            store = db.query(Store).filter(Store.name == store_name).first()
            if store:
                store_query = query.filter(OcrCorrection.store_id == store.id)
                if store_query.first():
                    query = store_query
                    scope = store_name

        rows = query.limit(limit).all()
        if not rows:
            return ""

        lines = [
            "",
            f"LEARNED CORRECTIONS (from past human reviews at {scope} — apply these patterns):",
        ]
        for c in rows:
            if c.field == "name":
                lines.append(f'- Extracted name "{c.ai_value}" was corrected to "{c.approved_value}".')
            elif c.field == "item_missed":
                lines.append(f'- A "{c.approved_value}" line was missed entirely — do not skip items.')
            elif c.field == "item_hallucinated":
                lines.append(f'- "{c.ai_value}" was extracted but is not a purchased item — do not invent lines.')
            elif c.field in ("price", "quantity"):
                lines.append(
                    f'- {c.field} for "{c.item_context}" was corrected from {c.ai_value} to {c.approved_value}.'
                )
        return "\n".join(lines) + "\n"
    except Exception:
        logger.exception("Failed to build correction prompt block")
        return ""
