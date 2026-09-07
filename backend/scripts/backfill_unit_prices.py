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
from app.utils.item_parsing import is_weight_priced, weighted_unit_price

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
    disputed: list[str] = []

    try:
        receipt_items = db.query(ReceiptItem).join(ReceiptItem.item).all()

        for ri in receipt_items:
            changed = False
            item_name = ri.item.name if ri.item else ""

            # --- 1. Extract weight/unit_type from the item name if missing ---
            # This runs BEFORE the price recompute, and tracks the result in a
            # local rather than reading it back off the row, so that a weight
            # discovered here reaches unit_price in the same pass and --dry-run
            # reports the same numbers a real run would write.
            effective_weight = ri.weight
            weight_from_name = False
            if (not ri.weight or ri.weight == 0) and item_name:
                w_val, w_unit = extract_size(item_name)
                if w_val:
                    effective_weight = w_val
                    weight_from_name = True
                    print(f"  [{ri.id}] {item_name[:40]:<40} weight: None → {w_val} {w_unit}")
                    if not dry_run:
                        ri.weight = w_val
                        ri.unit_type = w_unit
                    changed = True

            # --- 2. Recalculate price and unit_price from notes ---
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
                    # unit_price is the price of ONE unit of unit_type wherever
                    # a weight is known -- not only on bulk lines. Gating this on
                    # is_bulk left a per-package figure on every packaged line
                    # (984 of 1,584 in the live database) in a column items.py
                    # reads as $/oz.
                    #
                    # The stored is_bulk is deliberately NOT consulted. Rows
                    # written before the prompt was corrected set it true for any
                    # packaged weight label ("RUSSET POT 5LB"), so on historical
                    # data it does not separate a line priced by weight from a
                    # package that merely has a size on it. quantity == weight
                    # does -- but only for a weight that came off the receipt. A
                    # weight recovered from the name above is a package size even
                    # when quantity happens to equal it, so it never takes the
                    # weight-priced branch. No row in the corpus collides today;
                    # the rule is structural, not measured.
                    weight_priced = not weight_from_name and is_weight_priced(
                        qty, effective_weight
                    )
                    new_unit_price = weighted_unit_price(
                        final_price, qty, effective_weight, weight_priced
                    )
                    if new_unit_price is None:
                        new_unit_price = new_price

                    # A stored unit_price on a weight-priced line can be two
                    # different things. It may be the "@ $2.49/lb" the model read
                    # off the page, which is better evidence than re-deriving it
                    # from a total the same model extracted. Or it may be this
                    # bug's own output: dividing by quantity as well as weight,
                    # when on these lines quantity IS the weight, squares the
                    # divisor. All 50 such rows in the live database are the
                    # latter -- a $1.37 bunch of bananas over 1.54 lb stored as
                    # $0.58/lb, which is 1.37 / 1.54².
                    #
                    # So repair the ones carrying that signature, and for anything
                    # else report the disagreement and leave the value alone
                    # rather than silently overwriting it.
                    if weight_priced and ri.unit_price and ri.unit_price > 0:
                        squared = final_price / (qty * effective_weight)
                        over_divided = abs(ri.unit_price - squared) <= 0.01
                        if not over_divided and abs(ri.unit_price - new_unit_price) > 0.01:
                            disputed.append(
                                f"  [{ri.id}] {item_name[:40]:<40} "
                                f"stored {ri.unit_price}/{ri.unit_type}, but "
                                f"{final_price} over {effective_weight} works out at "
                                f"{new_unit_price} — left as-is"
                            )
                            new_unit_price = ri.unit_price

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

            if changed:
                updated += 1
            else:
                skipped += 1

        if disputed:
            print(
                f"\n⚠️  {len(disputed)} weight-priced lines whose stated price per unit "
                f"disagrees with their own total; none were changed:"
            )
            for line in disputed:
                print(line)

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
