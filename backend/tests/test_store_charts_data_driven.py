"""Per-store trend cards must come from the user's own data.

These cards were previously hardcoded to Amazon Fresh / Amazon.com / Whole
Foods / Costco, so they rendered as permanently blank boxes for anyone
shopping elsewhere. They are now derived from the stores with the most
receipts, with an explanatory empty state until receipts are uploaded.
"""

import json
from datetime import datetime, timedelta

from bs4 import BeautifulSoup

from app.models import Item, Receipt, ReceiptItem, Store

HARDCODED_IDS = ["chart-amazon-fresh", "chart-amazon-com", "chart-wholefoods", "chart-costco"]


def _seed(db, store_names, receipts_each=2):
    """Create stores, each with receipts for one repeatedly-bought item."""
    made = []
    for n, name in enumerate(store_names):
        store = Store(name=name)
        db.add(store)
        db.flush()
        item = Item(name=f"Item {name}")
        db.add(item)
        db.flush()
        for i in range(receipts_each + n):  # differing counts => deterministic ranking
            receipt = Receipt(
                store_id=store.id,
                purchase_date=datetime.now() - timedelta(days=7 * i + 1),
                status="completed",
                total_amount=3.0 + i,
            )
            db.add(receipt)
            db.flush()
            db.add(ReceiptItem(receipt_id=receipt.id, item_id=item.id, price=3.0 + i, quantity=1))
        made.append(store)
    db.commit()
    return made


def test_trends_page_renders_a_card_per_store_not_hardcoded_chains(client, db):
    _seed(db, ["Corner Shop", "Hilltop Market"])
    soup = BeautifulSoup(client.get("/trends").text, "html.parser")

    canvases = soup.select("#storeChartsContainer canvas[data-store-id]")
    names = sorted(c["data-store-name"] for c in canvases)
    assert names == ["Corner Shop", "Hilltop Market"]

    # the old hardcoded canvases must be gone
    for old_id in HARDCODED_IDS:
        assert soup.find(id=old_id) is None, f"{old_id} is still hardcoded"


def test_each_store_card_has_an_accessible_label_and_empty_state(client, db):
    _seed(db, ["Corner Shop"])
    soup = BeautifulSoup(client.get("/trends").text, "html.parser")

    canvas = soup.select_one("#storeChartsContainer canvas[data-store-id]")
    assert canvas["aria-label"] == "Corner Shop top item price trends line chart"
    assert canvas["id"] == f"chart-store-{canvas['data-store-id']}"

    msg = canvas.parent.select_one(".store-chart-empty")
    assert msg is not None and "Corner Shop" in msg.get_text()


def test_trends_page_explains_itself_when_there_are_no_stores(client):
    soup = BeautifulSoup(client.get("/trends").text, "html.parser")

    assert soup.select("#storeChartsContainer canvas[data-store-id]") == []
    container = soup.find(id="storeChartsContainer")
    assert "No stores yet" in container.get_text()
    assert "upload receipts" in container.get_text().lower()


def test_store_top_items_accepts_store_id(client, db):
    store = _seed(db, ["Corner Shop"], receipts_each=3)[0]

    resp = client.get(f"/api/trends/store-top-items?store_id={store.id}&time_range=year")
    assert resp.status_code == 200
    body = resp.json()
    assert body["labels"], "expected weekly labels for a store with receipts"
    assert body["datasets"], "expected at least one item series"

    # unknown id is empty, not an error; neither param is a 422
    assert client.get("/api/trends/store-top-items?store_id=999999").json() == {
        "labels": [],
        "datasets": [],
    }
    assert client.get("/api/trends/store-top-items").status_code == 422


def test_all_charts_fragment_keys_stores_by_id(client, db):
    stores = _seed(db, ["Corner Shop", "Hilltop Market"])
    text = client.get("/api/trends/fragment/all-charts").text

    payload = text.split("stores: ", 1)[1].split(",\n", 1)[0]
    stores_data = json.loads(payload)
    assert set(stores_data) == {str(s.id) for s in stores}
    for series in stores_data.values():
        assert "labels" in series and "datasets" in series
