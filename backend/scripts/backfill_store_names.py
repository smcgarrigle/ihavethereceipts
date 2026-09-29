"""
backfill_store_names.py
-----------------------
Fills the permanent store-name table (``store_item_aliases``) from receipts
already reviewed, so it starts with every store's history instead of empty.

Receipts are replayed in upload order through the same code a review save uses,
so where a store printed the same text for different items over time, the most
recent one wins, exactly as it would have if the table had existed all along.

Previews by default and writes nothing. Pass --apply to write. (Other backfill
scripts here write by default; this one fills a table the OCR pipeline reads on
every receipt, so writing is opt-in.)

Run from backend/:

    uv run python scripts/backfill_store_names.py            # preview
    uv run python scripts/backfill_store_names.py --apply    # write

    --apply   write the names; without it the run is rolled back
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models import Receipt, Store, StoreItemAlias
from app.services.store_names import BACKFILL_SOURCE, remember_receipt


def backfill(db) -> dict:
    """Replay every reviewed receipt in upload order. Does not commit."""
    receipts = (
        db.query(Receipt)
        .filter(Receipt.status == "completed", Receipt.ocr_data.isnot(None), Receipt.store_id.isnot(None))
        .order_by(Receipt.created_at, Receipt.id)
        .all()
    )
    used = sum(1 for receipt in receipts if remember_receipt(db, receipt, source=BACKFILL_SOURCE))
    db.flush()
    stores = dict(db.query(Store.id, Store.name).all())
    per_store = Counter(
        stores.get(store_id, "?") for (store_id,) in db.query(StoreItemAlias.store_id)
    )
    return {
        "receipts": len(receipts),
        "receipts_used": used,
        "names": sum(per_store.values()),
        "per_store": per_store,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fill store names from reviewed receipts.")
    parser.add_argument("--apply", action="store_true", help="write the names (default: preview)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        before = db.query(StoreItemAlias).count()
        report = backfill(db)
        print(f"Reviewed receipts replayed: {report['receipts']} ({report['receipts_used']} gave names)")
        print(f"Store names: {before} before, {report['names']} after")
        for store, count in report["per_store"].most_common(10):
            print(f"  {count:5d}  {store}")
        if args.apply:
            db.commit()
            print("Written.")
        else:
            db.rollback()
            print("Preview only: nothing written. Pass --apply to write.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
