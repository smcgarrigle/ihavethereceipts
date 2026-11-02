"""Tests for analytics exclusion rules applying to the X-Ray page.

Reproduces the bug where item-name exclusion patterns (e.g. "CRV")
were not filtering items from the X-Ray endpoint because the check
only matched against category names.
"""

import pytest

from app.api.analytics import _is_excluded
from app.models import Category, Item, Receipt, ReceiptItem, Store
from app.models.exclusion import ExclusionRule

# ── Unit tests for _is_excluded helper ───────────────────────────────


class TestIsExcluded:
    """Verify _is_excluded matches against both category and item names."""

    def test_matches_category_name(self):
        assert _is_excluded(["other"], cat_name="Other", item_name="Bananas")

    def test_matches_item_name(self):
        """Core bug reproduction: pattern 'crv' must match item name even
        when the category is 'Fees & Taxes' (no 'crv' substring)."""
        assert _is_excluded(["crv"], cat_name="Fees & Taxes", item_name="CRV 6PK UNDER 240Z AB")

    def test_matches_item_name_exact(self):
        assert _is_excluded(["crv"], cat_name="Other", item_name="CRV")

    def test_case_insensitive_item_match(self):
        assert _is_excluded(["ca redemp va"], cat_name="Other", item_name="CA REDEMP VA")

    def test_no_match(self):
        assert not _is_excluded(["crv"], cat_name="Produce", item_name="Banana")

    def test_empty_item_name(self):
        """When no item_name is given, only category is checked."""
        assert not _is_excluded(["crv"], cat_name="Produce")
        assert _is_excluded(["produce"], cat_name="Produce")

    def test_substring_match_on_item(self):
        """Pattern 'crv' should match any item containing 'crv'."""
        assert _is_excluded(
            ["crv"], cat_name="Fees & Taxes", item_name="CRV CRV Container Alcohol 6PK Under 24OZ"
        )


# ── Integration test: X-Ray endpoint filters excluded items ──────────


@pytest.fixture()
def seeded_db(db):
    """Seed the test DB with items, receipts, and an exclusion rule for 'crv'."""
    store = Store(name="Test Store")
    db.add(store)
    db.flush()

    cat_produce = Category(name="Produce")
    cat_fees = Category(name="Fees & Taxes")
    db.add_all([cat_produce, cat_fees])
    db.flush()

    item_banana = Item(name="Banana", category_id=cat_produce.id)
    item_crv = Item(name="CRV", category_id=cat_fees.id)
    item_crv_long = Item(name="CRV CRV Container Alcohol 6PK Under 24OZ", category_id=cat_fees.id)
    db.add_all([item_banana, item_crv, item_crv_long])
    db.flush()

    from datetime import datetime

    receipt = Receipt(
        store_id=store.id,
        status="completed",
        purchase_date=datetime(2026, 7, 1),
        total_amount=10.0,
    )
    db.add(receipt)
    db.flush()

    # 3 items on the receipt
    ri1 = ReceiptItem(receipt_id=receipt.id, item_id=item_banana.id, price=2.00, quantity=1)
    ri2 = ReceiptItem(receipt_id=receipt.id, item_id=item_crv.id, price=0.35, quantity=1)
    ri3 = ReceiptItem(receipt_id=receipt.id, item_id=item_crv_long.id, price=0.36, quantity=1)
    db.add_all([ri1, ri2, ri3])

    # Add exclusion rule for "crv" (item-name pattern)
    rule = ExclusionRule(scope="analytics", pattern="CRV")
    db.add(rule)
    db.commit()

    return db


def test_xray_excludes_items_by_name(client, seeded_db):  # noqa: ARG001
    """The X-Ray endpoint must exclude items whose *name* matches an
    exclusion pattern, even if the category name does not match."""
    resp = client.get("/api/analytics/receipt-xray")
    assert resp.status_code == 200
    data = resp.json()

    # Phantom Items should only contain Banana, not the CRV items
    phantom_names = [p["name"] for p in data.get("phantom_items", [])]
    assert "CRV" not in phantom_names
    assert "CRV CRV Container Alcohol 6PK Under 24OZ" not in phantom_names

    # Volatility should also not contain CRV items
    vol_names = [v["name"] for v in data.get("price_volatility", [])]
    assert "CRV" not in vol_names

    # Summary total_spend should not include CRV prices
    # Banana = $2.00, CRV items excluded → total should be $2.00
    assert data["summary"]["total_spend"] == 2.00


def test_thermal_grid_excludes_analytics_exclusions(db):
    """Price Heatmap (get_thermal_grid_data) on /trends must exclude items matching
    analytics ExclusionRule patterns (e.g. CRV, Driver tip:) and excluded categories."""
    from datetime import datetime

    from app.api.trends import get_thermal_grid_data

    s1 = Store(name="Store A")
    s2 = Store(name="Store B")
    cat_produce = Category(name="Produce")
    cat_fees = Category(name="Fees & Taxes")
    db.add_all([s1, s2, cat_produce, cat_fees])
    db.flush()

    banana = Item(name="Bananas", category_id=cat_produce.id)
    crv = Item(name="CRV", category_id=cat_fees.id)
    tip = Item(name="Driver tip:", category_id=cat_produce.id)
    db.add_all([banana, crv, tip])
    db.flush()

    for store in (s1, s2):
        r = Receipt(
            store_id=store.id,
            status="completed",
            purchase_date=datetime.now(),
            total_amount=10.0,
        )
        db.add(r)
        db.flush()
        for item, price in [(banana, 1.99), (crv, 0.10), (tip, 5.00)]:
            db.add(ReceiptItem(receipt_id=r.id, item_id=item.id, price=price, quantity=1))

    db.add_all(
        [
            ExclusionRule(scope="analytics", pattern="crv"),
            ExclusionRule(scope="analytics", pattern="driver tip:"),
        ]
    )
    db.commit()

    grid = get_thermal_grid_data(db, time_range="all")
    names = [item["name"] for item in grid["items"]]
    assert names == ["Bananas"]
    assert "CRV" not in names
    assert "Driver tip:" not in names


def test_exclusions_applied_across_best_value_nutrition_and_predictions(db):
    """Excluded items (by item-name pattern or excluded category) must not leak into
    Best Value tables, Nutrition Trends, Price Alerts, Top Items, or Restock Predictions."""
    from datetime import datetime, timedelta

    from app.api.analytics import _get_top_items, price_alerts, top_items
    from app.api.analytics_fragments import _get_category_price_data, get_top_items_html
    from app.api.trends_nutrition import _get_raw_nutrition_data, get_nutrition_coverage
    from app.services.predictions import _cadence_cache, get_item_cadences

    _cadence_cache["data"] = None

    store = Store(name="Store A")
    cat_bev = Category(name="Beverages")
    cat_fees = Category(name="Fees & Taxes")
    db.add_all([store, cat_bev, cat_fees])
    db.flush()

    juice = Item(
        name="Organic Apple Juice",
        category_id=cat_bev.id,
        nutrients={"sugars_100g": 10.0, "proteins_100g": 0.5, "fat_100g": 0.1, "sodium_100g": 0.01},
    )
    crv_bev = Item(
        name="CRV WINE SNGL TAX",
        category_id=cat_bev.id,
        nutrients={"sugars_100g": 50.0, "proteins_100g": 0.0, "fat_100g": 0.0, "sodium_100g": 0.0},
    )
    bag_fee = Item(
        name="CUSTOMER SERVICES Bag Refund",
        category_id=cat_fees.id,
        nutrients={"sugars_100g": 0.0, "proteins_100g": 10.0, "fat_100g": 0.0, "sodium_100g": 0.0},
    )
    tip = Item(
        name="Driver tip:",
        category_id=cat_bev.id,
    )
    db.add_all([juice, crv_bev, bag_fee, tip])
    db.flush()

    base = datetime.now() - timedelta(days=40)
    for i, mult in enumerate([1.0, 1.5, 2.0, 2.5]):
        r = Receipt(
            store_id=store.id,
            status="completed",
            purchase_date=base + timedelta(days=10 * i),
            total_amount=20.0,
        )
        db.add(r)
        db.flush()
        for item, base_price in [
            (juice, 4.00),
            (crv_bev, 0.10 * mult),
            (bag_fee, 0.25 * mult),
            (tip, 5.00 * mult),
        ]:
            db.add(
                ReceiptItem(
                    receipt_id=r.id,
                    item_id=item.id,
                    price=base_price,
                    quantity=1,
                    weight=16.0,
                    unit_type="oz",
                )
            )

    db.add_all(
        [
            ExclusionRule(scope="analytics", pattern="crv"),
            ExclusionRule(scope="analytics", pattern="driver tip:"),
            ExclusionRule(scope="predictions", pattern="crv"),
        ]
    )
    db.commit()

    # 1. Best Value Beverages must only contain Organic Apple Juice
    bv_names = [row["name"] for row in _get_category_price_data("Beverages", "beverages", db)]
    assert bv_names == ["Organic Apple Juice"]

    # 2. Nutrition raw data & coverage must only count Organic Apple Juice
    nutr_names = {row["item_name"] for row in _get_raw_nutrition_data("all", db)}
    assert nutr_names == {"Organic Apple Juice"}
    cov = get_nutrition_coverage("all", db)
    assert cov["total_items"] == 1

    # 3. Price Alerts, Top Items, and Basket _get_top_items must exclude CRV, Bag Refund, Driver tip
    alert_names = [a["item_name"] for a in price_alerts(threshold=5.0, db=db)]
    assert "CRV WINE SNGL TAX" not in alert_names
    assert "CUSTOMER SERVICES Bag Refund" not in alert_names
    assert "Driver tip:" not in alert_names

    top_names = [t["name"] for t in top_items(limit=10, db=db)]
    assert top_names == ["Organic Apple Juice"]
    assert "Driver tip:" not in get_top_items_html(limit=10, db=db)
    assert _get_top_items(db, limit=10) == [juice.id]

    # 4. Predictions cadences must exclude CRV, Driver tip, and Fees & Taxes items
    cadence_names = [c["item_name"] for c in get_item_cadences(db)]
    assert cadence_names == ["Organic Apple Juice"]
