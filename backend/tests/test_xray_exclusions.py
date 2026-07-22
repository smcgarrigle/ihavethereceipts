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
