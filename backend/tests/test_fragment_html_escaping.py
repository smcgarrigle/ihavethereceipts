"""Store/category/item names must be HTML-escaped in server-built fragments.

These names are user-controlled — the receipt review screen lets you type a
store name freely, and item/category names come from OCR of receipt images.
The analytics fragments build HTML by f-string interpolation, so an unescaped
name is stored XSS: a store saved as `"><img src=x onerror=...>` broke out of
its attribute and executed on every dashboard load.

Covers both contexts these names land in: plain HTML text/attributes, and a
JS string literal nested inside an HTML event attribute (which the browser
HTML-decodes *before* evaluating as JS, so it needs both escapings).
"""

from datetime import datetime

import pytest

from app.models.category import Category
from app.models.item import Item
from app.models.receipt import Receipt, ReceiptItem
from app.models.store import Store

ATTR_BREAKOUT = '"><img src=x onerror=alert(1)>'
JS_BREAKOUT = "');alert(1);//"

FRAGMENT_ENDPOINTS = [
    "/api/analytics/tables/store-spend",
    "/api/analytics/tables/top-categories",
    "/api/analytics/tables/top-items",
    "/api/analytics/widgets/category-store-stack",
]


def _seed(db, payload: str):
    category = Category(name=f"Bev {payload}")
    db.add(category)
    db.flush()

    item = Item(name=f"Water {payload}", normalized_name="water", category_id=category.id)
    db.add(item)
    db.flush()

    store = Store(name=f"Mart {payload}")
    db.add(store)
    db.flush()

    receipt = Receipt(
        store_id=store.id,
        total_amount=9.99,
        purchase_date=datetime(2026, 1, 15),
        status="completed",
    )
    db.add(receipt)
    db.flush()

    db.add(ReceiptItem(receipt_id=receipt.id, item_id=item.id, quantity=1, price=9.99))
    db.commit()


@pytest.mark.parametrize("payload", [ATTR_BREAKOUT, JS_BREAKOUT], ids=["attr", "js"])
@pytest.mark.parametrize("endpoint", FRAGMENT_ENDPOINTS)
def test_fragment_escapes_user_controlled_names(db, client, endpoint, payload):
    _seed(db, payload)

    body = client.get(endpoint).text

    assert payload not in body, (
        f"{endpoint} emitted a user-controlled name verbatim — the raw payload "
        f"{payload!r} reached the response, so it can break out of its HTML "
        "attribute or JS string. Escape with html.escape() (and json.dumps() "
        "first for JS-in-attribute contexts)."
    )
