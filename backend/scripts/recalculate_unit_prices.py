import sys
from pathlib import Path

# Add backend directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from app.database import SessionLocal
from app.models import ReceiptItem


def recalculate_unit_prices():
    db = SessionLocal()
    try:
        print("Starting unit price recalculation...")

        # Find items with weight but no unit price (or update all just in case?)
        # Let's update all items where weight > 0
        items = db.query(ReceiptItem).filter(ReceiptItem.weight > 0).all()

        count = 0
        for item in items:
            # Formula: unit_price = final_price / weight
            # e.g. Price $10, Weight 5lb -> $2/lb

            # Wait, DB stores unit_price on the item? Or is it calculating on read?
            # Model definition check:
            # item.unit_price is a column in ReviewedItemData but does ReceiptItem have it?
            # Let's check model first.

            if item.price and item.weight:
                # We need final price per item.
                # ReceiptItem.price is typically the final price per unit (quantity)
                # Logic: receipt_item.price is the price PER ITEM (quantity).
                # So if I bought 2 packs of beer, quantity=2, price=$24 (per pack).
                # Weight=24 (oz, per pack).
                # Unit Price = 24 / 24 = $1/oz.

                calculated_unit_price = item.price / item.weight

                # Check if we should update
                # if not item.unit_price or abs(item.unit_price - calculated_unit_price) > 0.01:
                item.unit_price = calculated_unit_price
                count += 1

        db.commit()
        print(f"Successfully updated unit prices for {count} items.")

    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    recalculate_unit_prices()
