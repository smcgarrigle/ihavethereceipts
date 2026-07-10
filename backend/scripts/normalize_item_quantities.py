import json
import logging
import re
import sys
from pathlib import Path

# Add the backend directory to the path so we can import app modules
backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

from app.database import SessionLocal
from app.models import Item, ReceiptItem

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def normalize_multipack_quantities():
    db = SessionLocal()
    try:
        # Regex to match pack sizes like "6pk", "12-pack", "24 pk", etc.
        pack_regex = re.compile(r"(\d+)\s*(?:pk|pack)", re.IGNORECASE)

        # 1. Find all items that are multipacks
        items = db.query(Item).all()
        multipack_items = []

        for item in items:
            match = pack_regex.search(item.name)
            if match:
                pack_size = int(match.group(1))
                # Only consider sensible pack sizes (e.g. 4, 6, 8, 12, 15, 18, 24, 30, 36)
                if pack_size in [4, 6, 8, 12, 15, 18, 20, 24, 30, 36]:
                    multipack_items.append((item, pack_size))

        logger.info(f"Found {len(multipack_items)} multipack items.")

        updates_made = 0

        # 2. Check receipt items for these multipack items
        for item, pack_size in multipack_items:
            receipt_items = db.query(ReceiptItem).filter(ReceiptItem.item_id == item.id).all()

            for ri in receipt_items:
                # If quantity is a multiple of the pack_size (and >= pack_size)
                # It means they tracked individual units (cans/bottles) instead of packs
                if ri.quantity >= pack_size and ri.quantity % pack_size == 0:
                    old_qty = ri.quantity
                    old_price = ri.price

                    new_qty = old_qty / pack_size
                    new_price = old_price * pack_size

                    ri.quantity = new_qty
                    ri.price = new_price

                    # Update calc_debug in notes if it exists
                    if ri.notes:
                        try:
                            notes_data = json.loads(ri.notes)
                            if "calc_debug" in notes_data:
                                # Re-write the debug string to reflect the new math
                                debug_str = notes_data["calc_debug"]
                                # Example: "9.99 - 0 + 0 = 9.99 (Total) / 6.0 = 1.665 (Unit)"
                                # We want to change the divisor and the final result
                                if "(Total) /" in debug_str:
                                    parts = debug_str.split("(Total) /")
                                    prefix = parts[0] + "(Total) /"
                                    notes_data["calc_debug"] = (
                                        f"{prefix} {new_qty} = {new_price} (Unit)"
                                    )
                                    ri.notes = json.dumps(notes_data)
                        except Exception as e:
                            logger.warning(
                                f"Failed to update calc_debug for ReceiptItem {ri.id}: {e}"
                            )

                    logger.info(
                        f"Receipt {ri.receipt_id} | Item: '{item.name}' "
                        f"| Normalized Qty: {old_qty} -> {new_qty} "
                        f"| Unit Price: {old_price:.2f} -> {new_price:.2f}"
                    )
                    updates_made += 1

        if updates_made > 0:
            db.commit()
            logger.info(f"Successfully normalized {updates_made} receipt items.")
        else:
            logger.info("No receipt items needed normalization.")

    except Exception as e:
        db.rollback()
        logger.error(f"Error during normalization: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    normalize_multipack_quantities()
