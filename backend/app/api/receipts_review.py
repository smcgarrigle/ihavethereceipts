"""Review-save flow: persisting human-reviewed receipt items.

Split out of receipts.py — mounted on the same /api/receipts prefix, so all
route paths are unchanged.
"""

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Receipt
from app.services.item_matcher import (
    find_merge_candidates,
    get_best_match,
    get_store_item_ids,
)
from app.services.spend import line_total
from app.utils.item_parsing import extract_weight

router = APIRouter()
logger = logging.getLogger(__name__)


class ReviewedItemData(BaseModel):
    name: str
    base_price: float
    quantity: float
    discounts: list[dict]
    fees: list[dict]
    final_price: float
    weight: float | None = None
    unit_type: str | None = None
    unit_price: float | None = None
    category: str | None = None
    original_unit_price: float | None = None
    total_discount: float | None = None
    is_bulk: bool | None = False
    fdc_match: dict | None = None

    from pydantic import field_validator

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Item name must not be empty")
        return v.strip()

    @field_validator("quantity")
    @classmethod
    def quantity_must_be_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Quantity must be non-negative")
        return v

    @field_validator("discounts", "fees")
    @classmethod
    def cast_amounts(cls, v: list[dict]) -> list[dict]:
        """Ensure all amount fields are floats, as they may come in as strings from the frontend"""
        if not v:
            return []
        for entry in v:
            if "amount" in entry:
                try:
                    entry["amount"] = float(entry["amount"])
                except (ValueError, TypeError):
                    entry["amount"] = 0.0
        return v


class SaveReviewedItemsRequest(BaseModel):
    items: list[ReviewedItemData]
    purchase_date: str | None = None
    store_name: str | None = None
    total_amount: float | None = None


@router.post("/{receipt_id}/save-reviewed-items")
def save_reviewed_items(
    receipt_id: int,
    request: SaveReviewedItemsRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Save items after manual review"""
    try:
        from sqlalchemy.exc import IntegrityError

        from app.models import Category, Item, ReceiptItem

        receipt = db.query(Receipt).filter(Receipt.id == receipt_id).first()
        if not receipt:
            raise HTTPException(status_code=404, detail="Receipt not found")

        # Guard: refuse an all-$0 payload before any DB writes. A payload where
        # every line total is zero has destroyed real totals before (July 2026:
        # 209 receipts) — the API is the last line of defense against a buggy
        # client or a misinstructed agent. Individual $0 lines (bag refunds,
        # CRV rows) remain legal as long as the receipt isn't all zeros.
        if request.items and not request.total_amount:
            line_totals = [
                (i.base_price or 0)
                - sum(float(d.get("amount", 0)) for d in (i.discounts or []))
                + sum(float(f.get("amount", 0)) for f in (i.fees or []))
                for i in request.items
            ]
            if all(t == 0 for t in line_totals):
                return {
                    "success": False,
                    "message": (
                        f"All {len(request.items)} items have $0.00 prices — refusing to save. "
                        "Set at least one item price (or the receipt total) and try again."
                    ),
                }

        # Update Metadata (Store and Date)
        if request.store_name:
            from app.models import Store
            from app.services.store_utils import normalize_store_name

            store_name = normalize_store_name(request.store_name)
            store = db.query(Store).filter(Store.name == store_name).first()
            if not store:
                try:
                    with db.begin_nested():
                        store = Store(name=store_name)
                        db.add(store)
                        db.flush()
                except IntegrityError:
                    store = db.query(Store).filter(Store.name == store_name).first()
            receipt.store_id = store.id

        if request.purchase_date:
            from datetime import datetime

            try:
                # Handle YYYY-MM-DD
                receipt.purchase_date = datetime.fromisoformat(request.purchase_date)
            except ValueError:
                pass

        if request.total_amount is not None:
            receipt.total_amount = request.total_amount

        items_saved = 0
        merge_suggestions = []

        # Clear existing items to prevent duplication (Idempotency fix)
        db.query(ReceiptItem).filter(ReceiptItem.receipt_id == receipt.id).delete()

        # OPTIMIZATION: Fetch all items and store history once to avoid N+1 queries
        all_items = db.query(Item).all()
        store_item_ids = get_store_item_ids(db, receipt.store_id)

        for reviewed_item in request.items:
            item_name = reviewed_item.name

            # Normalize item name for matching
            normalized_name = item_name.lower().strip()

            # Try exact match first
            item = next((i for i in all_items if i.normalized_name == normalized_name), None)

            # If no exact match, try fuzzy matching using pre-fetched list
            if not item:
                item = get_best_match(
                    item_name,
                    db,
                    threshold=85,
                    existing_items=all_items,
                    store_item_ids=store_item_ids,
                )

            # If still not found, create new item with user-provided category
            if not item:
                # Use category assigned from the frontend, or default to Other
                category_name = reviewed_item.category
                if not category_name:
                    category_name = "Other"
                else:
                    category_name = category_name.strip()
                    if not category_name:
                        category_name = "Other"
                    else:
                        category_name = category_name[:50].title()

                # Find or create category. Unknown names go through the
                # canonical interceptor so review data can't re-fragment the
                # taxonomy; existing (incl. user-created) categories pass as-is.
                category = db.query(Category).filter(Category.name == category_name).first()
                if not category:
                    from app.services.category_mapper import map_category_name

                    category_name = map_category_name(category_name)
                    category = db.query(Category).filter(Category.name == category_name).first()
                if not category:
                    try:
                        with db.begin_nested():
                            category = Category(name=category_name)
                            db.add(category)
                            db.flush()
                    except IntegrityError:
                        category = db.query(Category).filter(Category.name == category_name).first()

                item = Item(
                    name=item_name, normalized_name=normalized_name, category_id=category.id
                )
                # Use FDC match from request if provided
                if reviewed_item.fdc_match:
                    item.fdc_id = reviewed_item.fdc_match.get("fdc_id")
                    item.gtin = reviewed_item.fdc_match.get("gtin")

                # Flush before scheduling: item.id is only assigned here, and
                # the enrichment task needs it.
                db.add(item)
                db.flush()

                if not reviewed_item.fdc_match:
                    # Trigger FDC Enrichment in background
                    from app.services.fdc_service import enrich_db_item_task

                    background_tasks.add_task(enrich_db_item_task, item.id)

                # Add to our local list for subsequent iterations
                all_items.append(item)

                print(f"✓ Created item '{item_name}' in category '{category_name}'")

                # Check for potential duplicates using pre-fetched list
                candidates = find_merge_candidates(item_name, item.id, db, existing_items=all_items)
                if candidates:
                    merge_suggestions.append(
                        {
                            "new_item": {"id": item.id, "name": item_name},
                            "candidates": candidates[:3],
                        }
                    )
            else:
                # UPDATE EXISTING ITEM CATEGORY IF CHANGED BY USER
                category_name = reviewed_item.category
                if category_name and category_name != "Other":
                    if not item.category or item.category.name != category_name:
                        category = db.query(Category).filter(Category.name == category_name).first()
                        if not category:
                            from app.services.category_mapper import map_category_name

                            category_name = map_category_name(category_name)
                            category = (
                                db.query(Category).filter(Category.name == category_name).first()
                            )
                        if not category:
                            try:
                                with db.begin_nested():
                                    category = Category(name=category_name)
                                    db.add(category)
                                    db.flush()
                            except IntegrityError:
                                category = (
                                    db.query(Category)
                                    .filter(Category.name == category_name)
                                    .first()
                                )

                        item.category_id = category.id
                        print(
                            f"✓ Updated existing item '{item.name}' to category '{category_name}'"
                        )

            # Calculate final price server-side for safety
            total_discount = sum(float(d.get("amount", 0)) for d in (reviewed_item.discounts or []))
            total_fees = sum(float(f.get("amount", 0)) for f in (reviewed_item.fees or []))
            calculated_line_total = (reviewed_item.base_price or 0) - total_discount + total_fees

            # Determine Unit Price to store in 'price' column (Server logic: price is Unit Price)
            qty = reviewed_item.quantity if reviewed_item.quantity > 0 else 1.0
            price_per_unit = calculated_line_total / qty

            notes_data = {
                "base_price": reviewed_item.base_price,
                "discounts": reviewed_item.discounts,
                "fees": reviewed_item.fees,
                "is_bulk": reviewed_item.is_bulk,
                "calc_debug": f"{reviewed_item.base_price} - {total_discount} + {total_fees} = {calculated_line_total} (Total) / {qty} = {price_per_unit} (Unit)",
            }

            # Automated Weight Extraction: If weight is missing, try to extract from name
            final_weight = reviewed_item.weight
            final_unit = reviewed_item.unit_type

            if not final_weight or final_weight == 0:
                ext_val, ext_unit = extract_weight(item_name)
                if ext_val:
                    final_weight = ext_val
                    final_unit = ext_unit

            receipt_item = ReceiptItem(
                receipt_id=receipt.id,
                item_id=item.id,
                quantity=qty,
                price=price_per_unit,
                notes=json.dumps(notes_data),
                weight=final_weight,
                unit_type=final_unit,
                unit_price=reviewed_item.unit_price,
                original_unit_price=reviewed_item.original_unit_price,
                total_discount=reviewed_item.total_discount,
            )
            db.add(receipt_item)
            items_saved += 1

        db.flush()

        # Update receipt total to match sum of items and mark as completed.
        # Never clobber a known-good total with $0: fall back to the client's
        # stated total, then to whatever the receipt already had.
        item_sum = sum(line_total(ri) for ri in receipt.items)
        receipt.total_amount = (
            item_sum if item_sum > 0 else (request.total_amount or receipt.total_amount)
        )
        receipt.status = "completed"

        # Feedback loop: persist the human's fixes as few-shot signal for future OCR
        from app.services.correction_service import record_corrections

        recorded = record_corrections(db, receipt, request.items)
        if recorded:
            logger.info(f"Recorded {recorded} OCR corrections for receipt {receipt.id}")

        db.commit()

        return {
            "success": True,
            "items_saved": items_saved,
            "merge_suggestions": merge_suggestions,
        }
    except Exception as e:
        db.rollback()
        import traceback

        traceback.print_exc()
        logger.error(f"Error saving reviewed items for receipt {receipt_id}: {e}")
        return {"success": False, "message": str(e)}
