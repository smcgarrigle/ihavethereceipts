import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import func

# Load environment variables from .env
load_dotenv()

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import SessionLocal
from app.models import Item, Receipt, ReceiptItem, Store
from app.services.category_tagger import categorize_item
from app.services.pdf_parser import parse_pdf_receipt

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def sync_receipts(folder_path: str, dry_run: bool = True):
    db = SessionLocal()
    folder = Path(folder_path)
    if not folder.exists():
        logger.error(f"Folder not found: {folder_path}")
        return

    logger.info(f"--- Starting Sync from {folder_path} (Recursive, Dry Run={dry_run}) ---")

    stats = {"processed": 0, "enriched": 0, "created": 0, "skipped": 0, "errors": 0}

    # Find all PDFs recursively
    pdf_files = list(folder.rglob("*.pdf"))
    logger.info(f"Found {len(pdf_files)} PDF files.")

    for pdf_path in pdf_files:
        stats["processed"] += 1
        try:
            logger.info(f"Processing: {pdf_path.relative_to(folder)}")
            data = parse_pdf_receipt(str(pdf_path))

            if not data or not data.get("order_number"):
                logger.warning("  Skipping: No order data extracted.")
                stats["skipped"] += 1
                continue

            order_num = data["order_number"]
            data["store_name"]
            total = data["total_amount"]
            date_str = data["purchase_date"]
            items_data = data.get("items", [])

            # 1. Check by Order Number
            receipt = db.query(Receipt).filter(Receipt.order_number == order_num).first()

            # 2. Check by Store/Date/Total if Order Number search fails
            if not receipt and date_str:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                # Find "empty" receipts that match this metadata
                receipt = (
                    db.query(Receipt)
                    .filter(
                        Receipt.total_amount == total, func.date(Receipt.purchase_date) == dt.date()
                    )
                    .first()
                )  # Simplified check

            if receipt:
                # Enrichment path
                item_count = (
                    db.query(ReceiptItem).filter(ReceiptItem.receipt_id == receipt.id).count()
                )
                if item_count == 0:
                    logger.info(
                        f"  Enriching Receipt ID {receipt.id} with {len(items_data)} items."
                    )
                    if not dry_run:
                        receipt.order_number = order_num
                        receipt.ocr_data = json.dumps(data)
                        _save_items(db, receipt, items_data)
                        stats["enriched"] += 1
                else:
                    logger.info(f"  Skipping: Receipt ID {receipt.id} already has items.")
                    stats["skipped"] += 1
            else:
                # Creation path
                logger.info(f"  Creating new receipt for Order {order_num}")
                if not dry_run:
                    _create_receipt(db, data, str(pdf_path))
                    stats["created"] += 1
                else:
                    stats["created"] += 1

        except Exception as e:
            logger.error(f"  Error processing {pdf_path.name}: {e}")
            stats["errors"] += 1

        # Batch commit every 10 receipts
        if stats["processed"] % 10 == 0 and not dry_run:
            db.commit()
            logger.info("  --- Batch Commit ---")

    if not dry_run:
        db.commit()

    db.close()
    logger.info("--- Sync Finished ---")
    logger.info(json.dumps(stats, indent=2))
    return stats


# Local cache for categorization to avoid redundant API calls
ITEM_CACHE = {}
# Local cache for categories to avoid redundant DB queries
CATEGORY_CACHE = {}


def _save_items(db, receipt, items_data):
    import time

    from app.models import Category

    for item_data in items_data:
        # Simple item mapping/creation
        item_name = item_data["name"]

        # Check database first
        item = db.query(Item).filter(Item.name == item_name).first()
        if not item:
            # Check local cache next for item category
            if item_name in ITEM_CACHE:
                category_name = ITEM_CACHE[item_name]
            else:
                logger.info(f"    Categorizing new item: {item_name}")
                try:
                    category_name = categorize_item(item_name)
                    ITEM_CACHE[item_name] = category_name
                    # Rate limiting for free tier (15 RPM)
                    time.sleep(5)
                except Exception as e:
                    logger.warning(f"    Categorization failed for {item_name}: {e}")
                    category_name = "Other"

            # Find or create the Category object (fixing the previous crash)
            if category_name in CATEGORY_CACHE:
                cat_obj = CATEGORY_CACHE[category_name]
            else:
                cat_obj = db.query(Category).filter(Category.name == category_name).first()
                if not cat_obj:
                    cat_obj = Category(name=category_name)
                    db.add(cat_obj)
                    db.flush()
                CATEGORY_CACHE[category_name] = cat_obj

            item = Item(name=item_name, category=cat_obj)
            db.add(item)
            db.flush()

        ri = ReceiptItem(
            receipt_id=receipt.id,
            item_id=item.id,
            quantity=item_data.get("quantity", 1),
            price=item_data.get("final_price", 0),
            unit_price=item_data.get("unit_price"),
        )
        db.add(ri)


def _create_receipt(db, data, file_path):
    # Find or create store
    store_name = data["store_name"]
    store = db.query(Store).filter(Store.name == store_name).first()
    if not store:
        store = Store(name=store_name)
        db.add(store)
        db.flush()

    dt = datetime.now()
    if data.get("purchase_date"):
        dt = datetime.strptime(data["purchase_date"], "%Y-%m-%d")

    receipt = Receipt(
        store_id=store.id,
        image_path=file_path,
        total_amount=data["total_amount"],
        purchase_date=dt,
        order_number=data["order_number"],
        status="completed",
        ocr_data=json.dumps(data),
    )
    db.add(receipt)
    db.flush()
    _save_items(db, receipt, data.get("items", []))


if __name__ == "__main__":
    # Folder of receipt PDFs to sync. Override with a CLI arg or PDF_SYNC_FOLDER;
    # defaults to data/GroceryReceiptsPDFs at the project root.
    root_dir = Path(__file__).parent.parent.parent
    default_folder = root_dir / "data" / "GroceryReceiptsPDFs"
    folder = sys.argv[1] if len(sys.argv) > 1 else os.getenv("PDF_SYNC_FOLDER", str(default_folder))
    # Execute actual sync
    sync_receipts(folder, dry_run=False)
