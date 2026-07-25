"""Tests for the Purchase Cadence Engine and Prediction API endpoints."""

from datetime import datetime, timedelta

from app.models.category import Category
from app.models.item import Item
from app.models.receipt import Receipt, ReceiptItem
from app.models.store import Store


def _create_item_with_purchases(
    db, item_name, store_name, purchase_dates, price=5.99, category_name="Groceries"
):
    """Helper: create a store, category, item, and receipts at given dates."""
    store = db.query(Store).filter(Store.name == store_name).first()
    if not store:
        store = Store(name=store_name)
        db.add(store)
        db.flush()

    category = db.query(Category).filter(Category.name == category_name).first()
    if not category:
        category = Category(name=category_name)
        db.add(category)
        db.flush()

    item = Item(name=item_name, normalized_name=item_name.lower(), category_id=category.id)
    db.add(item)
    db.flush()

    for purchase_date in purchase_dates:
        receipt = Receipt(
            store_id=store.id,
            total_amount=price,
            purchase_date=purchase_date,
            status="completed",
        )
        db.add(receipt)
        db.flush()

        ri = ReceiptItem(receipt_id=receipt.id, item_id=item.id, quantity=1, price=price)
        db.add(ri)

    db.commit()
    return item


class TestCadenceCalculation:
    """Test the core cadence math in predictions.py."""

    def test_cadence_calculation_basic(self, db):
        """Items with regular 14-day intervals should produce avg_interval ≈ 14."""
        from app.services.predictions import get_item_cadences

        base = datetime(2026, 1, 1)
        dates = [base + timedelta(days=14 * i) for i in range(5)]
        _create_item_with_purchases(db, "Test Milk", "TestMart", dates)

        cadences = get_item_cadences(db)
        assert len(cadences) == 1

        c = cadences[0]
        assert c["item_name"] == "Test Milk"
        assert c["purchase_count"] == 5
        assert c["avg_interval"] == 14.0
        assert c["std_interval"] == 0.0
        assert c["predicted_exhaustion"] is not None

    def test_minimum_purchase_threshold(self, db):
        """Items with fewer than 3 purchases should NOT appear in cadences."""
        from app.services.predictions import get_item_cadences

        base = datetime(2026, 1, 1)
        dates = [base, base + timedelta(days=7)]  # Only 2 purchases
        _create_item_with_purchases(db, "Rare Item", "TestMart", dates)

        cadences = get_item_cadences(db)
        assert len(cadences) == 0

    def test_shopping_list_filters_urgent(self, db):
        """Shopping list should only include high/overdue non-stale items."""
        from app.services.predictions import get_shopping_list

        today = datetime.now()

        # Create an overdue item (last bought 30 days ago, 7-day cycle)
        overdue_dates = [today - timedelta(days=30 + 7 * i) for i in range(4)]
        _create_item_with_purchases(db, "Daily Bread", "TestMart", overdue_dates)

        # Create a low-urgency item (last bought yesterday, 30-day cycle)
        low_dates = [today - timedelta(days=1 + 30 * i) for i in range(4)]
        _create_item_with_purchases(db, "Monthly Spice", "TestMart", low_dates)

        shopping = get_shopping_list(db)
        names = [item["item_name"] for item in shopping]

        # Daily Bread should be overdue, Monthly Spice should not be urgent
        assert "Daily Bread" in names
        assert "Monthly Spice" not in names

    def test_stale_items_excluded(self, db):
        """Items last purchased 7+ months ago should be flagged stale."""
        from app.services.predictions import get_item_cadences, get_shopping_list

        today = datetime.now()
        # Last purchase was 7 months ago, with a monthly cadence
        stale_dates = [today - timedelta(days=210 + 30 * i) for i in range(4)]
        _create_item_with_purchases(db, "Old Cereal", "TestMart", stale_dates)

        cadences = get_item_cadences(db)
        assert len(cadences) == 1
        assert cadences[0]["stale"] is True

        # Should NOT appear in shopping list
        shopping = get_shopping_list(db)
        assert len(shopping) == 0

    def test_cadence_adapts_to_habit_change(self, db):
        """A long-history item that shifts cadence should predict from recent
        behavior (trailing MAX_CADENCE_INTERVALS window), not the full archive."""
        from app.services.predictions import MAX_CADENCE_INTERVALS, get_item_cadences

        base = datetime(2025, 6, 1)
        # Ten months of monthly purchases...
        dates = [base + timedelta(days=30 * i) for i in range(11)]
        # ...then the habit changes: eight weekly purchases
        weekly_start = dates[-1]
        dates += [weekly_start + timedelta(days=7 * i) for i in range(1, MAX_CADENCE_INTERVALS + 1)]
        _create_item_with_purchases(db, "Oat Milk", "TestMart", dates)

        cadences = get_item_cadences(db)
        assert len(cadences) == 1

        c = cadences[0]
        assert c["purchase_count"] == len(dates)
        # Full-history mean would be ~19.8 days; the trailing window sees only
        # the eight weekly intervals.
        assert c["avg_interval"] == 7.0
        assert c["std_interval"] == 0.0

    def test_store_prices_present(self, db):
        """Each cadence entry should have store price comparisons."""
        from app.services.predictions import get_item_cadences

        base = datetime(2026, 1, 1)
        dates = [base + timedelta(days=10 * i) for i in range(4)]
        _create_item_with_purchases(db, "Eggs", "CostCo", dates, price=3.49)

        # Add a second store's purchase
        store2 = Store(name="Safeway")
        db.add(store2)
        db.flush()
        item = db.query(Item).filter(Item.name == "Eggs").first()
        r = Receipt(
            store_id=store2.id,
            total_amount=4.99,
            purchase_date=base + timedelta(days=45),
            status="completed",
        )
        db.add(r)
        db.flush()
        ri = ReceiptItem(receipt_id=r.id, item_id=item.id, quantity=1, price=4.99)
        db.add(ri)
        db.commit()

        cadences = get_item_cadences(db)
        assert len(cadences) == 1
        assert len(cadences[0]["store_prices"]) == 2
        # Best price should be first
        assert cadences[0]["store_prices"][0]["price"] <= cadences[0]["store_prices"][1]["price"]


class TestPredictionAPI:
    """Test the API endpoints via TestClient."""

    def test_ics_feed_removed(self, client):
        """ICS endpoint should be removed and return 404."""
        response = client.get("/api/predictions/calendar.ics")
        assert response.status_code == 404

    def test_stats_endpoint(self, client):
        """Stats endpoint should return valid JSON with expected keys."""
        response = client.get("/api/predictions/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_tracked" in data
        assert "urgent_count" in data
        assert "overdue_count" in data
        assert "stale_count" in data
        assert "avg_cadence_days" in data

    def test_shopping_list_endpoint(self, client):
        """Shopping list endpoint should return a JSON list."""
        response = client.get("/api/predictions/shopping-list")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_cadences_endpoint(self, client):
        """Cadences endpoint should return a JSON list."""
        response = client.get("/api/predictions/cadences")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_restock_page(self, client):
        """Restock page should render with 200 status."""
        response = client.get("/restock")
        assert response.status_code == 200
        assert "Restock Predictions" in response.text
