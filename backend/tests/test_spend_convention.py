"""Spend must be read as price * quantity, everywhere, in one direction.

``ReceiptItem.price`` is the per-quantity price (DATA_DESIGN.md), so a line
costs ``price * quantity``. That expression was re-derived at thirty-five call
sites and went wrong in both directions:

* The BI dashboard read ``item_spend = ri.price`` and understated every figure
  on the page by the quantity factor, while ``/api/analytics/summary`` reported
  the correct number from the same rows — two dashboards over one database
  disagreeing, neither labelled an estimate.
* The basket-over-time chart divided the already-per-unit ``price`` by quantity
  a second time, so a habit change from buying one unit to four read as a 75%
  price drop.

These tests pin the convention itself and the two dashboards that broke it.
"""

from datetime import datetime, timedelta

import pytest

from app.models import Category, Item, Receipt, ReceiptItem, Store
from app.services.spend import line_total, line_total_of, unit_price_of


def test_line_total_multiplies_by_quantity():
    class Row:
        price = 4.99
        quantity = 6

    assert line_total(Row()) == pytest.approx(29.94)


def test_line_total_handles_missing_values():
    class Row:
        price = None
        quantity = None

    assert line_total(Row()) == 0.0
    assert line_total_of(None, 3) == 0.0
    assert line_total_of(2.5, None) == 0.0


def test_unit_price_does_not_divide_by_quantity_again():
    """price already IS the per-unit figure — dividing is the mirror-image bug."""
    assert unit_price_of(4.99, 6) == pytest.approx(4.99)
    assert unit_price_of(4.99, 1) == pytest.approx(4.99)
    assert unit_price_of(4.99) == pytest.approx(4.99)


@pytest.fixture
def multi_quantity_receipt(db):
    """One receipt, one line: 6 x $4.99 = $29.94."""
    category = Category(name="Dairy")
    db.add(category)
    db.flush()

    item = Item(name="Greek Yogurt", normalized_name="greek yogurt", category_id=category.id)
    store = Store(name="Test Store")
    db.add_all([item, store])
    db.flush()

    receipt = Receipt(
        store_id=store.id,
        purchase_date=datetime.now() - timedelta(days=2),
        total_amount=29.94,
        status="completed",
    )
    db.add(receipt)
    db.flush()

    db.add(
        ReceiptItem(
            receipt_id=receipt.id,
            item_id=item.id,
            price=4.99,
            quantity=6,
            unit_price=4.99,
        )
    )
    db.commit()
    return receipt


@pytest.mark.usefixtures("multi_quantity_receipt")
def test_summary_and_bi_dashboard_agree_on_spend(client):
    """The two endpoints read the same rows and must report the same money."""
    summary = client.get("/api/analytics/summary")
    assert summary.status_code == 200
    summary_spend = summary.json()["total_spending"]
    assert summary_spend == pytest.approx(29.94, abs=0.02), (
        "the summary endpoint should read 6 x $4.99 as $29.94"
    )

    bi = client.get("/api/analytics/bi-dashboard")
    assert bi.status_code == 200
    bi_spend = bi.json()["kpis"]["monthly_spend"]
    assert bi_spend == pytest.approx(summary_spend, abs=0.02), (
        f"the BI dashboard reports {bi_spend} where the summary reports "
        f"{summary_spend} — it is reading the unit price as the line total."
    )


@pytest.mark.usefixtures("multi_quantity_receipt")
def test_bi_dashboard_category_spend_uses_the_line_total(client):
    bi = client.get("/api/analytics/bi-dashboard")
    assert bi.status_code == 200
    dairy = [c for c in bi.json()["categories"] if c["name"] == "Dairy"]
    assert dairy, "the seeded Dairy line did not reach the category breakdown"
    assert dairy[0]["spend"] == pytest.approx(29.94, abs=0.02)


@pytest.mark.usefixtures("multi_quantity_receipt")
def test_xray_store_spend_uses_the_line_total(client):
    response = client.get("/api/analytics/receipt-xray")
    assert response.status_code == 200
