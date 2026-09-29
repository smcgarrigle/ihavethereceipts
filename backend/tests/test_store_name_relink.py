"""CM-23: when a store's printed text comes to mean a different item, offer to
move the past lines too.

The review save reports each store name that now points at a different item,
with how many past lines are still on the old one. The page previews them and
moves exactly those; purchase history changes only after a preview.
"""

import json

from app.models import Item, Receipt, ReceiptItem, Store
from app.services import store_names
from app.services.store_names import remember_receipt


def _store(db, name="Costco"):
    store = db.query(Store).filter_by(name=name).first()
    if not store:
        store = Store(name=name)
        db.add(store)
        db.commit()
    return store


def _item(db, name):
    item = Item(name=name, normalized_name=name.lower().strip())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _saved(db, store, lines):
    """A reviewed receipt; ``lines`` is [(item, text the model read, price)]. Remembered."""
    receipt = Receipt(
        status="completed",
        store_id=store.id,
        image_path="/data/uploads/a.jpg",
        ocr_data=json.dumps(
            {
                "items": [
                    {"name": read, "final_price": price, "quantity": 1} for _, read, price in lines
                ]
            }
        ),
    )
    db.add(receipt)
    db.commit()
    for item, _, price in lines:
        db.add(ReceiptItem(receipt_id=receipt.id, item_id=item.id, price=price, quantity=1))
    db.commit()
    remember_receipt(db, receipt)
    db.commit()
    return receipt


def _pending(db, store, read, price=3.99):
    receipt = Receipt(
        store_id=store.id,
        status="review",
        image_path="/data/uploads/new.jpg",
        ocr_data=json.dumps({"items": [{"name": read, "final_price": price, "quantity": 1}]}),
    )
    db.add(receipt)
    db.commit()
    return receipt


def _save(client, receipt, name, price=3.99):
    body = {
        "items": [
            {
                "name": name,
                "base_price": price,
                "quantity": 1,
                "discounts": [],
                "fees": [],
                "final_price": price,
                "category": "",
            }
        ]
    }
    return client.post(f"/api/receipts/{receipt.id}/save-reviewed-items", json=body).json()


def _lines_on(db, item):
    return db.query(ReceiptItem).filter_by(item_id=item.id).count()


# ---------------------------------------------------------------------------
# The review save reports it
# ---------------------------------------------------------------------------


def test_a_save_that_changes_a_store_name_offers_the_past_lines(db, client):
    costco = _store(db)
    potato = _item(db, "Potato Chips")
    for _ in range(3):
        _saved(db, costco, [(potato, "CHIPS", 3.99)])

    body = _save(client, _pending(db, costco, "CHIPS"), "Corn Chips")

    [offer] = body["relink_suggestions"]
    assert offer["store"] == "Costco"
    assert offer["printed_text"] == "CHIPS"
    assert (offer["from_item"], offer["to_item"]) == ("Potato Chips", "Corn Chips")
    assert offer["lines"] == 3


def test_a_save_that_keeps_the_same_item_offers_nothing(db, client):
    costco = _store(db)
    potato = _item(db, "Potato Chips")
    _saved(db, costco, [(potato, "CHIPS", 3.99)])

    body = _save(client, _pending(db, costco, "CHIPS"), "Potato Chips")

    assert body["relink_suggestions"] == []


def test_a_first_save_of_new_text_offers_nothing(db, client):
    costco = _store(db)

    body = _save(client, _pending(db, costco, "CHIPS"), "Corn Chips")

    assert body["relink_suggestions"] == []


def test_a_failure_finding_past_lines_does_not_fail_the_save(db, client, monkeypatch):
    costco = _store(db)
    _saved(db, costco, [(_item(db, "Potato Chips"), "CHIPS", 3.99)])

    def broken(*_args, **_kwargs):
        raise RuntimeError("lookup failed")

    monkeypatch.setattr(store_names, "relink_suggestions", broken)
    body = _save(client, _pending(db, costco, "CHIPS"), "Corn Chips")

    assert body["success"] is True
    assert body["relink_suggestions"] == []


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def _preview(client, store, key, old, new, **extra):
    params = {
        "store_id": store.id,
        "text_key": key,
        "from_item_id": old.id,
        "to_item_id": new.id,
        **extra,
    }
    return client.get("/api/store-names/relink/preview", params=params)


def test_the_preview_lists_only_lines_with_that_text_at_that_store_on_the_old_item(db, client):
    costco, safeway = _store(db, "Costco"), _store(db, "Safeway")
    potato, corn, salsa = _item(db, "Potato Chips"), _item(db, "Corn Chips"), _item(db, "Salsa")
    wanted = _saved(db, costco, [(potato, "CHIPS", 3.99), (salsa, "SALSA", 4.49)])
    _saved(db, costco, [(potato, "KTL CHIPS", 3.99)])  # other text, same item
    _saved(db, safeway, [(potato, "CHIPS", 2.99)])  # other store
    _saved(db, costco, [(corn, "CHIPS", 3.99)])  # already on the new item

    lines = _preview(client, costco, "chips", potato, corn).json()["lines"]

    assert [line["receipt_id"] for line in lines] == [wanted.id]
    assert lines[0]["price"] == 3.99


def test_the_preview_leaves_out_the_receipt_being_saved(db, client):
    costco = _store(db)
    potato, corn = _item(db, "Potato Chips"), _item(db, "Corn Chips")
    first = _saved(db, costco, [(potato, "CHIPS", 3.99)])
    second = _saved(db, costco, [(potato, "CHIPS", 3.99)])

    lines = _preview(client, costco, "CHIPS", potato, corn, exclude_receipt_id=second.id).json()[
        "lines"
    ]

    assert [line["receipt_id"] for line in lines] == [first.id]


def test_the_preview_finds_text_far_from_the_item_name(db, client):
    costco = _store(db)
    potato, corn, milk = _item(db, "Potato Chips"), _item(db, "Corn Chips"), _item(db, "Milk")
    # A code shares nothing with the name, so only the unique-price step links it.
    receipt = _saved(db, costco, [(milk, "MILK", 4.49), (potato, "ITEM 44172", 3.99)])

    lines = _preview(client, costco, "ITEM 44172", potato, corn).json()["lines"]

    assert [line["receipt_id"] for line in lines] == [receipt.id]


def test_the_preview_rejects_an_unknown_item(db, client):
    costco = _store(db)
    potato = _item(db, "Potato Chips")
    params = {
        "store_id": costco.id,
        "text_key": "chips",
        "from_item_id": potato.id,
        "to_item_id": 99999,
    }

    assert client.get("/api/store-names/relink/preview", params=params).status_code == 404


# ---------------------------------------------------------------------------
# Moving
# ---------------------------------------------------------------------------


def _move(client, store, key, old, new, line_ids):
    body = {
        "store_id": store.id,
        "text_key": key,
        "from_item_id": old.id,
        "to_item_id": new.id,
        "line_ids": line_ids,
    }
    return client.post("/api/store-names/relink", json=body)


def test_moving_changes_the_previewed_lines(db, client):
    costco = _store(db)
    potato, corn = _item(db, "Potato Chips"), _item(db, "Corn Chips")
    for _ in range(3):
        _saved(db, costco, [(potato, "CHIPS", 3.99)])
    ids = [
        line["line_id"] for line in _preview(client, costco, "CHIPS", potato, corn).json()["lines"]
    ]

    body = _move(client, costco, "CHIPS", potato, corn, ids).json()

    assert body == {"success": True, "moved": 3}
    assert _lines_on(db, potato) == 0
    assert _lines_on(db, corn) == 3


def test_only_previewed_lines_move(db, client):
    costco = _store(db)
    potato, corn = _item(db, "Potato Chips"), _item(db, "Corn Chips")
    for _ in range(3):
        _saved(db, costco, [(potato, "CHIPS", 3.99)])
    ids = [
        line["line_id"] for line in _preview(client, costco, "CHIPS", potato, corn).json()["lines"]
    ]

    _move(client, costco, "CHIPS", potato, corn, ids[:1])

    assert _lines_on(db, potato) == 2


def test_a_line_changed_since_the_preview_is_left_alone(db, client):
    costco = _store(db)
    potato, corn, kettle = (
        _item(db, "Potato Chips"),
        _item(db, "Corn Chips"),
        _item(db, "Kettle Chips"),
    )
    _saved(db, costco, [(potato, "CHIPS", 3.99)])
    [line] = _preview(client, costco, "CHIPS", potato, corn).json()["lines"]
    edited = db.get(ReceiptItem, line["line_id"])
    edited.item_id = kettle.id
    db.commit()

    body = _move(client, costco, "CHIPS", potato, corn, [line["line_id"]]).json()

    assert body["moved"] == 0
    db.refresh(edited)
    assert edited.item_id == kettle.id


def test_a_line_id_that_was_never_a_candidate_is_ignored(db, client):
    costco = _store(db)
    potato, corn, salsa = _item(db, "Potato Chips"), _item(db, "Corn Chips"), _item(db, "Salsa")
    receipt = _saved(db, costco, [(potato, "CHIPS", 3.99), (salsa, "SALSA", 4.49)])
    salsa_line = db.query(ReceiptItem).filter_by(receipt_id=receipt.id, item_id=salsa.id).one()

    body = _move(client, costco, "CHIPS", salsa, corn, [salsa_line.id]).json()

    assert body["moved"] == 0
    assert _lines_on(db, salsa) == 1


def test_swapping_the_items_moves_them_back(db, client):
    costco = _store(db)
    potato, corn = _item(db, "Potato Chips"), _item(db, "Corn Chips")
    _saved(db, costco, [(potato, "CHIPS", 3.99)])
    ids = [
        line["line_id"] for line in _preview(client, costco, "CHIPS", potato, corn).json()["lines"]
    ]
    _move(client, costco, "CHIPS", potato, corn, ids)

    back = [
        line["line_id"] for line in _preview(client, costco, "CHIPS", corn, potato).json()["lines"]
    ]
    _move(client, costco, "CHIPS", corn, potato, back)

    assert _lines_on(db, potato) == 1
    assert _lines_on(db, corn) == 0


def test_moving_rejects_an_unknown_store(db, client):
    potato, corn = _item(db, "Potato Chips"), _item(db, "Corn Chips")
    body = {
        "store_id": 99999,
        "text_key": "chips",
        "from_item_id": potato.id,
        "to_item_id": corn.id,
        "line_ids": [],
    }

    assert client.post("/api/store-names/relink", json=body).status_code == 404


# ---------------------------------------------------------------------------
# The review page
# ---------------------------------------------------------------------------


def test_the_review_page_has_the_dialog(db, client):
    from bs4 import BeautifulSoup

    costco = _store(db)
    soup = BeautifulSoup(
        client.get(f"/receipts/{_pending(db, costco, 'CHIPS').id}/review").text, "html.parser"
    )

    dialog = soup.find(attrs={"aria-labelledby": "relink-title"})
    assert dialog is not None
    assert dialog.get("role") == "dialog"
    assert dialog.get("x-trap") == "relinkOpen"
    assert soup.find(id="relink-title") is not None
