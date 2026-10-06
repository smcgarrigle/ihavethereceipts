from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Category, Item, Receipt, ReceiptItem, Store
from app.services.volatility import get_volatile_items


def test_get_volatile_items(db: Session):
    # Setup test data
    store = Store(name="Test Store")
    category = Category(name="Test Category")
    db.add(store)
    db.add(category)
    db.commit()

    # Item 1: High volatility (>15%)
    item1 = Item(name="Volatile Item", category_id=category.id, normalized_name="volatile item")
    # Item 2: Low volatility (<15%)
    item2 = Item(name="Stable Item", category_id=category.id, normalized_name="stable item")
    # Item 3: Downward volatility (<-15%)
    item3 = Item(name="Dropping Item", category_id=category.id, normalized_name="dropping item")

    db.add_all([item1, item2, item3])
    db.commit()

    now = datetime.now()
    recent_date = now - timedelta(days=10)
    historical_date = now - timedelta(days=60)

    def add_purchase(item, date, price):
        receipt = Receipt(store_id=store.id, purchase_date=date, total_amount=price)
        db.add(receipt)
        db.commit()

        ri = ReceiptItem(
            receipt_id=receipt.id,
            item_id=item.id,
            quantity=1,
            price=price,
            unit_type="each",
            original_unit_price=price,
            total_discount=0,
        )
        db.add(ri)
        db.commit()

    # Volatile item: historical avg $10, recent avg $12.5 (25% increase)
    add_purchase(item1, historical_date, 10.0)
    add_purchase(item1, recent_date, 12.5)

    # Stable item: historical avg $10, recent avg $10.5 (5% increase)
    add_purchase(item2, historical_date, 10.0)
    add_purchase(item2, recent_date, 10.5)

    # Dropping item: historical avg $10, recent avg $7.5 (25% decrease)
    add_purchase(item3, historical_date, 10.0)
    add_purchase(item3, recent_date, 7.5)

    # Calculate volatility
    volatile_items = get_volatile_items(db, threshold_pct=0.15, days=30)

    # Should only return item1 and item3
    assert len(volatile_items) == 2

    item_names = [x["item_name"] for x in volatile_items]
    assert "Volatile Item" in item_names
    assert "Dropping Item" in item_names
    assert "Stable Item" not in item_names

    # Check specifics
    for v in volatile_items:
        if v["item_name"] == "Volatile Item":
            assert v["shift_pct"] == 25.0
            assert v["trend"] == "up"
        elif v["item_name"] == "Dropping Item":
            assert v["shift_pct"] == -25.0
            assert v["trend"] == "down"
