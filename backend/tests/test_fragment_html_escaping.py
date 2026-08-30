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
    # Added after the audit: these build markup the same way and had no escaping.
    "/api/items/list",
    "/api/analytics/tables/best-value/beverages",
    "/api/analytics/tables/best-value/beverages/rows",
]


def _seed(db, payload: str):
    category = Category(name=f"Beverages {payload}")
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


# ---------------------------------------------------------------------------
# The endpoints below need their own shape of data, so they cannot ride on the
# parametrized list above. All three built markup by f-string interpolation
# with no escaping at all.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", [ATTR_BREAKOUT, JS_BREAKOUT], ids=["attr", "js"])
def test_duplicates_fragment_escapes_item_names(db, client, payload):
    """Two near-identical OCR names group together and both get rendered."""
    category = Category(name="Pantry")
    db.add(category)
    db.flush()

    db.add_all(
        [
            Item(
                name=f"Olive Oil {payload}",
                normalized_name=f"olive oil {payload}",
                category_id=category.id,
            ),
            Item(
                name=f"Olive Oil {payload} ",
                normalized_name=f"olive oil  {payload}",
                category_id=category.id,
            ),
        ]
    )
    db.commit()

    body = client.get("/api/items/duplicates").text
    assert payload not in body, "the duplicates fragment emitted an OCR-derived item name verbatim"


@pytest.mark.parametrize("payload", [ATTR_BREAKOUT, JS_BREAKOUT], ids=["attr", "js"])
def test_ignored_suggestions_fragment_escapes_item_names(db, client, payload):
    from app.models.item import ItemMatchIgnore

    category = Category(name="Pantry")
    db.add(category)
    db.flush()

    first = Item(name=f"Rice {payload}", normalized_name="rice a", category_id=category.id)
    second = Item(name=f"Rice {payload} 2", normalized_name="rice b", category_id=category.id)
    db.add_all([first, second])
    db.flush()
    db.add(ItemMatchIgnore(item_id_1=first.id, item_id_2=second.id))
    db.commit()

    body = client.get("/api/items/ignored-suggestions").text
    assert payload not in body, (
        "the ignored-suggestions fragment emitted an OCR-derived item name verbatim"
    )


@pytest.mark.parametrize("payload", [ATTR_BREAKOUT, JS_BREAKOUT], ids=["attr", "js"])
def test_bulk_queue_fragment_escapes_the_upload_filename(db, client, payload):
    """The multipart filename is attacker-supplied and this view auto-refreshes."""
    store = Store(name="Bulk Store")
    db.add(store)
    db.flush()

    db.add(
        Receipt(
            store_id=store.id,
            total_amount=0.0,
            purchase_date=datetime(2026, 1, 15),
            status="failed",
            notes=f"Bulk upload: {payload}.jpg",
            error_message=f"could not read {payload}",
        )
    )
    db.commit()

    body = client.get("/api/bulk/active-items").text
    assert payload not in body, (
        "the bulk queue emitted the client-supplied filename or the raw error "
        "message verbatim — this view refreshes itself every three seconds"
    )
