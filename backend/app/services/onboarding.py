import datetime
import logging

from sqlalchemy.orm import Session

from app.models import Category, Item, Receipt, ReceiptItem, Store

logger = logging.getLogger(__name__)


def populate_demo_data(db: Session) -> bool:
    """
    Populates the database with realistic demonstration data for new users.
    Creates stores, categories, items, receipts, and receipt items.
    """
    try:
        # 1. Categories mapping
        categories_to_seed = [
            "Produce",
            "Dairy",
            "Meat",
            "Bakery",
            "Pantry",
            "Beverages",
            "Frozen",
            "Household",
        ]
        categories_map = {}
        for cat_name in categories_to_seed:
            cat = db.query(Category).filter(Category.name == cat_name).first()
            if not cat:
                cat = Category(name=cat_name)
                db.add(cat)
                db.flush()  # get ID
            categories_map[cat_name] = cat

        # 2. Stores mapping
        stores_to_seed = ["Trader Joe's", "Safeway", "Costco"]
        stores_map = {}
        for store_name in stores_to_seed:
            store = db.query(Store).filter(Store.name == store_name).first()
            if not store:
                store = Store(name=store_name, address=f"{store_name} Main St")
                db.add(store)
                db.flush()  # get ID
            stores_map[store_name] = store

        # 3. Helper to get or create items
        def get_or_create_item(name: str, category_name: str) -> Item:
            normalized_name = name.strip().lower()
            item = db.query(Item).filter(Item.normalized_name == normalized_name).first()
            if not item:
                item = Item(
                    name=name,
                    normalized_name=normalized_name,
                    category_id=categories_map[category_name].id,
                )
                db.add(item)
                db.flush()
            return item

        # 4. Create Receipts
        today = datetime.datetime.now(datetime.UTC).date()

        # Receipt 1: Trader Joe's (5 days ago)
        tjs_store = stores_map["Trader Joe's"]
        tjs_date = today - datetime.timedelta(days=5)
        tjs_receipt = Receipt(
            store_id=tjs_store.id,
            total_amount=45.50,
            purchase_date=datetime.datetime.combine(tjs_date, datetime.time.min),
            notes="DEMO_DATA",
            status="completed",
        )
        db.add(tjs_receipt)
        db.flush()

        # Add items to Receipt 1
        items_1 = [
            ("Organic Bananas", "Produce", 1.0, 2.49, "lb", 1.0),
            ("Whole Milk", "Dairy", 1.0, 4.29, "each", None),
            ("Grass-Fed Ground Beef", "Meat", 1.0, 8.99, "lb", 1.0),
            ("Organic Avocados", "Produce", 4.0, 1.25, "each", None),
            ("Sourdough Bread", "Bakery", 1.0, 4.99, "each", None),
        ]
        for name, cat, qty, price, unit_type, weight in items_1:
            item = get_or_create_item(name, cat)
            ri = ReceiptItem(
                receipt_id=tjs_receipt.id,
                item_id=item.id,
                quantity=qty,
                price=price * qty,
                unit_price=price,
                unit_type=unit_type,
                weight=weight,
                original_unit_price=price,
                total_discount=0.0,
            )
            db.add(ri)

        # Receipt 2: Safeway (15 days ago)
        safeway_store = stores_map["Safeway"]
        safeway_date = today - datetime.timedelta(days=15)
        safeway_receipt = Receipt(
            store_id=safeway_store.id,
            total_amount=32.40,
            purchase_date=datetime.datetime.combine(safeway_date, datetime.time.min),
            notes="DEMO_DATA",
            status="completed",
        )
        db.add(safeway_receipt)
        db.flush()

        # Add items to Receipt 2 (includes some discounts)
        items_2 = [
            ("Whole Milk", "Dairy", 1.0, 4.49, "each", None),
            ("Honey Nut Cheerios", "Pantry", 2.0, 4.99, "each", None),
            ("Organic Bananas", "Produce", 1.2, 2.49, "lb", 1.2),
            ("Boneless Chicken Breast", "Meat", 1.0, 9.99, "each", None),
        ]
        for name, cat, qty, price, unit_type, weight in items_2:
            item = get_or_create_item(name, cat)
            ri = ReceiptItem(
                receipt_id=safeway_receipt.id,
                item_id=item.id,
                quantity=qty,
                price=price * qty,
                unit_price=price,
                unit_type=unit_type,
                weight=weight,
                original_unit_price=price,
                total_discount=0.0,
            )
            db.add(ri)

        # Receipt 3: Costco (25 days ago)
        costco_store = stores_map["Costco"]
        costco_date = today - datetime.timedelta(days=25)
        costco_receipt = Receipt(
            store_id=costco_store.id,
            total_amount=120.80,
            purchase_date=datetime.datetime.combine(costco_date, datetime.time.min),
            notes="DEMO_DATA",
            status="completed",
        )
        db.add(costco_receipt)
        db.flush()

        # Add items to Receipt 3
        items_3 = [
            ("Organic Bananas", "Produce", 1.0, 6.49, "each", None),
            ("Ribeye Steak", "Meat", 1.0, 45.99, "each", None),
            ("Grass-Fed Ground Beef", "Meat", 2.0, 8.49, "lb", 2.0),
            ("Paper Towels", "Household", 1.0, 29.99, "each", None),
            ("Sourdough Bread", "Bakery", 1.0, 4.49, "each", None),
        ]
        for name, cat, qty, price, unit_type, weight in items_3:
            item = get_or_create_item(name, cat)
            ri = ReceiptItem(
                receipt_id=costco_receipt.id,
                item_id=item.id,
                quantity=qty,
                price=price * qty,
                unit_price=price,
                unit_type=unit_type,
                weight=weight,
                original_unit_price=price,
                total_discount=0.0,
            )
            db.add(ri)

        db.commit()
        logger.info("Successfully populated onboarding demonstration data.")
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to populate demonstration data: {e}")
        return False


def clear_demo_data(db: Session) -> bool:
    """
    Clears all receipts containing notes="DEMO_DATA" and associated items.
    Also cleans up any orphaned master Item records.
    """
    try:
        # 1. Fetch and delete all demo receipts (cascade deletes ReceiptItems)
        demo_receipts = db.query(Receipt).filter(Receipt.notes == "DEMO_DATA").all()
        for receipt in demo_receipts:
            db.delete(receipt)
        db.flush()

        # 2. Find and delete all master items that have no receipt items left
        # This keeps the product database perfectly clean.
        db.query(Item).filter(~Item.receipt_items.any()).delete(synchronize_session=False)

        db.commit()
        logger.info("Successfully cleared all demonstration data and orphaned items.")
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to clear demonstration data: {e}")
        return False
