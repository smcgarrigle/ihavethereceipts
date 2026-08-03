"""SC 1.4.1 (Use of Color): the category/store spend-stack widget colors each
store's segment differently with no legend, and narrow segments hide their
overlaid store-name text entirely — color was the only way to identify them.
Also, the segments were plain non-interactive <div>s with only an onclick,
so they were unreachable by keyboard. Verifies both are fixed: each segment
is keyboard-focusable and carries an aria-label naming the store and amount
regardless of its rendered width.
"""

from datetime import datetime

from app.models.category import Category
from app.models.item import Item
from app.models.receipt import Receipt, ReceiptItem
from app.models.store import Store


def _seed_category_store_data(db):
    category = Category(name="Beverages")
    db.add(category)
    db.flush()

    item = Item(name="Sparkling Water", normalized_name="sparkling water", category_id=category.id)
    db.add(item)
    db.flush()

    for store_name, price in [("Costco", 12.99), ("Safeway", 8.49)]:
        store = Store(name=store_name)
        db.add(store)
        db.flush()

        receipt = Receipt(
            store_id=store.id,
            total_amount=price,
            purchase_date=datetime(2026, 1, 15),
            status="completed",
        )
        db.add(receipt)
        db.flush()

        db.add(ReceiptItem(receipt_id=receipt.id, item_id=item.id, quantity=1, price=price))

    db.commit()


def test_category_store_stack_segments_are_keyboard_accessible_and_labeled(db, client):
    _seed_category_store_data(db)

    resp = client.get("/api/analytics/widgets/category-store-stack")
    assert resp.status_code == 200

    html = resp.text
    assert 'role="button"' in html
    assert 'tabindex="0"' in html
    assert "aria-label=" in html
    # Each store's name+amount must be present in an aria-label, not just
    # inferable from segment color.
    assert "Costco:" in html
    assert "Safeway:" in html
