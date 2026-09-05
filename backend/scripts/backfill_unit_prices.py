"""
backfill_unit_prices.py
-----------------------
One-off migration to fix already-saved ReceiptItems so that:
  1. unit_price is derived from the actual paid price (final_price = base_price - discounts + fees)
     instead of the raw MSRP base_price.
  2. weight and unit_type are extracted from item names where missing (e.g. "RUSSET POT 5LB").

The two price columns mean different things and this script must keep them apart:
``price`` is the per-quantity price the whole app multiplies by quantity to get
spend (see app/services/spend.py and DATA_DESIGN.md), while ``unit_price`` is the
effective price per unit of weight for bulk lines. Writing the per-pound figure
into ``price`` turns a $3.99 five-pound bag of potatoes into eighty cents of
recorded spend.

Run from the backend/ directory:
    python scripts/backfill_unit_prices.py

Use --dry-run to preview changes without writing to the DB.
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Allow imports from the app
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models.receipt import ReceiptItem

# Same regex as ocr.py size extraction
SIZE_RE = re.compile(r"([\d\.]+)\s*(oz|lb|g|kg|ml|l|gal|pt|qt|ct|pk)\b", re.IGNORECASE)


def extract_size(name: str):
    """Return (weight_val, unit_str) or (None, None)."""
    m = SIZE_RE.search(name)
    if m:
        try:
            return float(m.group(1)), m.group(2).lower()
        except ValueError:
            pass
    return None, None


def backfill(dry_run: bool = False):
    db = SessionLocal()
    updated = 0
    skipped = 0

    try:
        receipt_items = db.query(ReceiptItem).join(ReceiptItem.item).all()

        for ri in receipt_items:
            changed = False
            item_name = ri.item.name if ri.item else ""

            # --- 1. Recalculate unit_price from notes (final_price / qty) ---
            if ri.notes:
                try:
                    notes = json.loads(ri.notes)
                    base_price = notes.get("base_price", 0) or 0
                    discounts = sum(d.get("amount", 0) for d in notes.get("discounts", []))
                    fees = sum(f.get("amount", 0) for f in notes.get("fees", []))
                    final_price = round(base_price - discounts + fees, 2)
                    qty = ri.quantity if ri.quantity and ri.quantity > 0 else 1

                    # price is the per-quantity price in every query (spend is
                    # price * quantity), so it is final_price / qty whatever the
                    # line is. Only unit_price carries the per-weight figure.
                    new_price = round(final_price / qty, 4)
                    if notes.get("is_bulk") and ri.weight and ri.weight > 0:
                        new_unit_price = round(final_price / (qty * ri.weight), 4)
                    else:
                        new_unit_price = new_price

                    unit_price_changed = abs((ri.unit_price or 0) - new_unit_price) > 0.0001
                    price_changed = abs((ri.price or 0) - new_price) > 0.0001

                    if unit_price_changed or price_changed:
                        print(
                            f"  [{ri.id}] {item_name[:40]:<40} price: {ri.price} → {new_price}, "
                            f"unit_price: {ri.unit_price} → {new_unit_price}  (final={final_price}, qty={qty})"
                        )
                        if not dry_run:
                            ri.unit_price = new_unit_price
                            ri.price = new_price
                        changed = True

                except (json.JSONDecodeError, TypeError, KeyError) as e:
                    print(f"  [{ri.id}] Could not parse notes: {e}")

            # --- 2. Extract weight/unit_type from item name if missing ---
            if (not ri.weight or ri.weight == 0) and item_name:
                w_val, w_unit = extract_size(item_name)
                if w_val:
                    print(f"  [{ri.id}] {item_name[:40]:<40} weight: None → {w_val} {w_unit}")
                    if not dry_run:
                        ri.weight = w_val
                        ri.unit_type = w_unit
                    changed = True

            if changed:
                updated += 1
            else:
                skipped += 1

        if not dry_run:
            db.commit()
            print(f"\n✅ Backfill complete: {updated} items updated, {skipped} items unchanged.")
        else:
            print(f"\n🔍 Dry run: {updated} items would be updated, {skipped} items unchanged.")

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill unit prices and weight extraction")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    args = parser.parse_args()
    backfill(dry_run=args.dry_run)
