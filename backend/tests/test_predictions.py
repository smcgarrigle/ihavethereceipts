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


class TestMedianCadenceAndRegularity:
    """Median interval + regularity labels (see predictions.REGULAR_CV)."""

    def test_median_ignores_a_single_outlier_gap(self, db):
        """
        One bulk-buy gap should not drag the cycle. Intervals 7,7,7,120 give a
        mean of ~35 days but a median of 7 — the habit is weekly.
        """
        from app.services.predictions import get_item_cadences

        base = datetime(2026, 1, 1)
        offsets = [0, 7, 14, 21, 141]  # three 7-day gaps, then a 120-day gap
        dates = [base + timedelta(days=o) for o in offsets]
        _create_item_with_purchases(db, "Weekly Bread", "TestMart", dates)

        c = get_item_cadences(db)[0]
        assert c["avg_interval"] == 7.0, "median must not be pulled by the 120-day gap"

    def test_regularity_labels_track_variability(self, db):
        """A metronomic item is 'regular'; a wildly spaced one is 'erratic'."""
        from app.services.predictions import get_item_cadences

        base = datetime(2026, 1, 1)
        steady = [base + timedelta(days=14 * i) for i in range(5)]
        _create_item_with_purchases(db, "Steady Milk", "TestMart", steady)

        jumpy = [base + timedelta(days=o) for o in (0, 2, 40, 45, 200)]
        _create_item_with_purchases(db, "Jumpy Sauce", "TestMart", jumpy)

        by_name = {c["item_name"]: c for c in get_item_cadences(db)}
        assert by_name["Steady Milk"]["cv"] == 0.0
        assert by_name["Steady Milk"]["regularity"] == "regular"
        assert by_name["Jumpy Sauce"]["cv"] > 1.0
        assert by_name["Jumpy Sauce"]["regularity"] == "erratic"


class TestCanonicalVariantHomogenization:
    """Layer 1 + Layer 2: canonical retail-title grouping in predictions."""

    def test_canonical_variants_pooled_in_cadences(self, db):
        """Buying 'Amazon Grocery, Russet Potatoes,' resets 'Russet Potatoes, 5 Lb' cadence."""
        from app.services.predictions import get_item_cadences

        today = datetime.now()
        # 3 purchases of "Russet Potatoes, 5 Lb" 84, 56, and 28 days ago (would be due today/overdue alone)
        older_dates = [today - timedelta(days=d) for d in (84, 56, 28)]
        item_main = _create_item_with_purchases(
            db,
            "Russet Potatoes, 5 Lb",
            "Whole Foods Market",
            older_dates,
            price=3.42,
            category_name="Produce",
        )

        # 1 recent purchase yesterday under "Amazon Grocery, Russet Potatoes,"
        item_variant = _create_item_with_purchases(
            db,
            "Amazon Grocery, Russet Potatoes,",
            "Amazon Fresh",
            [today - timedelta(days=1)],
            price=2.47,
            category_name="Produce",
        )

        cadences = get_item_cadences(db)
        assert len(cadences) == 1

        c = cadences[0]
        assert c["item_id"] == item_main.id
        assert c["item_name"] == "Russet Potatoes, 5 Lb"
        assert c["purchase_count"] == 4
        assert c["urgency"] == "low"
        assert len(c["variant_items"]) == 1
        assert c["variant_items"][0]["item_id"] == item_variant.id
        assert c["variant_items"][0]["item_name"] == "Amazon Grocery, Russet Potatoes,"

    def test_ignored_duplicate_pairs_stay_separate_in_cadences(self, db):
        """Pairs dismissed in ItemMatchIgnore must not be pooled in predictions."""
        from app.models.item import ItemMatchIgnore
        from app.services.predictions import get_item_cadences

        today = datetime.now()
        older_dates = [today - timedelta(days=d) for d in (42, 28, 14)]
        item1 = _create_item_with_purchases(
            db, "Russet Potatoes, 5 Lb", "Whole Foods Market", older_dates, category_name="Produce"
        )
        item2 = _create_item_with_purchases(
            db,
            "Amazon Grocery, Russet Potatoes,",
            "Amazon Fresh",
            [today - timedelta(days=1)],
            category_name="Produce",
        )

        ids = sorted([item1.id, item2.id])
        db.add(ItemMatchIgnore(item_id_1=ids[0], item_id_2=ids[1]))
        db.commit()

        cadences = get_item_cadences(db)
        assert len(cadences) == 1
        assert cadences[0]["purchase_count"] == 3
        assert cadences[0]["variant_items"] == []

    def test_restock_table_renders_variant_merge_badge(self, client, db):
        """/api/predictions/restock-table renders the variant badge + Merge button when variants exist."""
        today = datetime.now()
        # 2 older purchases under main item + 1 purchase 20 days ago under variant -> 3 total, overdue on 10d cycle
        _create_item_with_purchases(
            db,
            "2% Reduced Fat Milk, Half Gallon, 64 Fl Oz",
            "Whole Foods Market",
            [today - timedelta(days=40), today - timedelta(days=30)],
            price=4.29,
            category_name="Dairy",
        )
        _create_item_with_purchases(
            db,
            "Amazon Grocery, 2% Reduced Fat Milk, Half Gallon, 64 Fl Oz",
            "Amazon Fresh",
            [today - timedelta(days=20)],
            price=1.94,
            category_name="Dairy",
        )

        resp = client.get("/api/predictions/restock-table")
        assert resp.status_code == 200
        assert "+1 variant" in resp.text
        assert "mergeVariants()" in resp.text


# ---------------------------------------------------------------------------
# Dismissing an item from predictions
# ---------------------------------------------------------------------------


def _due_item(db, name="Egg Nog", store="TestMart"):
    """An item bought every 14 days whose next purchase is overdue."""
    last = datetime.now() - timedelta(days=20)
    dates = [last - timedelta(days=14 * i) for i in range(4)]
    return _create_item_with_purchases(db, name, store, dates)


def _buy(db, item, when):
    receipt = Receipt(
        store_id=db.query(Store).first().id,
        total_amount=5.99,
        purchase_date=when,
        status="completed",
    )
    db.add(receipt)
    db.flush()
    db.add(ReceiptItem(receipt_id=receipt.id, item_id=item.id, quantity=1, price=5.99))
    db.commit()


def _backdate(db, item, days):
    """Move a dismissal's start into the past, as if it had been made then."""
    from app.models import PredictionDismissal

    row = db.query(PredictionDismissal).filter_by(item_id=item.id).one()
    row.created_at -= timedelta(days=days)
    if row.until is not None:
        row.until -= timedelta(days=days)
    db.commit()


class TestPredictionDismissal:
    def test_a_dismissed_item_leaves_every_prediction_surface(self, client, db):
        from app.services.predictions import get_item_cadences, get_prediction_stats

        item = _due_item(db)
        assert "Egg Nog" in client.get("/api/predictions/optimized-list").text

        response = client.post(f"/api/predictions/dismiss/{item.id}", data={"period": "week"})

        assert response.status_code == 200
        assert get_item_cadences(db) == []
        assert get_prediction_stats(db)["total_tracked"] == 0
        assert client.get("/api/predictions/shopping-list").json() == []
        assert client.get("/api/predictions/cadences").json() == []
        assert "Egg Nog" not in client.get("/api/predictions/optimized-list").text
        assert "Egg Nog" not in client.get("/api/predictions/restock-table").text

    def test_other_items_stay(self, client, db):
        item = _due_item(db)
        _due_item(db, "Whole Milk")

        client.post(f"/api/predictions/dismiss/{item.id}", data={"period": "forever"})

        names = [c["item_name"] for c in client.get("/api/predictions/cadences").json()]
        assert names == ["Whole Milk"]

    def test_the_response_offers_undo_and_asks_the_page_to_refresh(self, client, db):
        item = _due_item(db)

        response = client.post(f"/api/predictions/dismiss/{item.id}", data={"period": "month"})

        assert response.headers["HX-Trigger"] == "restock-changed"
        assert 'id="restock-notice"' in response.text
        assert "for 1 month" in response.text
        assert f"/api/predictions/dismiss/{item.id}/restore" in response.text

    def test_restore_brings_the_item_back(self, client, db):
        item = _due_item(db)
        client.post(f"/api/predictions/dismiss/{item.id}", data={"period": "forever"})

        response = client.post(f"/api/predictions/dismiss/{item.id}/restore")

        assert "Restored" in response.text
        assert response.headers["HX-Trigger"] == "restock-changed"
        assert len(client.get("/api/predictions/cadences").json()) == 1

    def test_the_dismissed_list_says_when_each_item_returns(self, client, db):
        timed, permanent = _due_item(db), _due_item(db, "Cranberries")
        client.post(f"/api/predictions/dismiss/{permanent.id}", data={"period": "forever"})
        client.post(f"/api/predictions/dismiss/{timed.id}", data={"period": "week"})

        body = client.get("/api/predictions/dismissed").text

        back_on = (datetime.now() + timedelta(days=7)).strftime("%Y-%m")
        assert f"Back on {back_on}" in body
        assert "Dismissed for good" in body
        # Soonest to return first, permanent ones last.
        assert body.index("Egg Nog") < body.index("Cranberries")
        assert "HX-Trigger" not in client.get("/api/predictions/dismissed").headers

    def test_the_dismissed_list_is_empty_when_nothing_is_dismissed(self, client, db):
        _due_item(db)

        assert "Dismissed" not in client.get("/api/predictions/dismissed").text

    def test_a_timed_dismissal_ends_when_its_time_is_up(self, client, db):
        from app.services.predictions import get_item_cadences

        item = _due_item(db)
        client.post(f"/api/predictions/dismiss/{item.id}", data={"period": "week"})
        _backdate(db, item, 8)

        assert len(get_item_cadences(db)) == 1
        assert "Egg Nog" not in client.get("/api/predictions/dismissed").text

    def test_a_week_is_still_running_on_day_six(self, client, db):
        from app.services.predictions import get_item_cadences

        item = _due_item(db)
        client.post(f"/api/predictions/dismiss/{item.id}", data={"period": "week"})
        _backdate(db, item, 6)

        assert get_item_cadences(db) == []

    def test_buying_the_item_again_ends_a_timed_dismissal(self, client, db):
        from app.services.predictions import get_item_cadences

        item = _due_item(db)
        client.post(f"/api/predictions/dismiss/{item.id}", data={"period": "month"})
        _backdate(db, item, 3)
        _buy(db, item, datetime.now() - timedelta(days=1))

        assert len(get_item_cadences(db)) == 1

    def test_buying_the_item_again_does_not_end_a_permanent_dismissal(self, client, db):
        from app.services.predictions import get_item_cadences

        item = _due_item(db)
        client.post(f"/api/predictions/dismiss/{item.id}", data={"period": "forever"})
        _backdate(db, item, 3)
        _buy(db, item, datetime.now() - timedelta(days=1))

        assert get_item_cadences(db) == []

    def test_dismissing_again_replaces_the_earlier_decision(self, client, db):
        from app.models import PredictionDismissal

        item = _due_item(db)
        client.post(f"/api/predictions/dismiss/{item.id}", data={"period": "week"})
        client.post(f"/api/predictions/dismiss/{item.id}", data={"period": "forever"})

        rows = db.query(PredictionDismissal).all()
        assert len(rows) == 1
        assert rows[0].until is None

    def test_the_dismissal_is_not_tied_to_a_store(self, client, db):
        item = _due_item(db)
        _buy(db, item, datetime.now() - timedelta(days=90))
        other = Store(name="OtherMart")
        db.add(other)
        db.commit()

        client.post(f"/api/predictions/dismiss/{item.id}", data={"period": "week"})

        assert "Egg Nog" not in client.get("/api/predictions/optimized-list").text

    def test_an_unknown_period_is_rejected(self, client, db):
        item = _due_item(db)

        assert (
            client.post(f"/api/predictions/dismiss/{item.id}", data={"period": "year"}).status_code
            == 422
        )
        assert len(client.get("/api/predictions/cadences").json()) == 1

    def test_an_unknown_item_is_a_404(self, client):
        assert (
            client.post("/api/predictions/dismiss/999", data={"period": "week"}).status_code == 404
        )
        assert client.post("/api/predictions/dismiss/999/restore").status_code == 404

    def test_a_merge_carries_the_dismissal_to_the_kept_item(self, client, db):
        from app.models import PredictionDismissal

        dismissed, kept = _due_item(db), _due_item(db, "Egg Nog Quart")
        client.post(f"/api/predictions/dismiss/{dismissed.id}", data={"period": "forever"})

        client.post(
            "/api/items/merge", json={"keep_item_id": kept.id, "merge_item_ids": [dismissed.id]}
        )

        assert [row.item_id for row in db.query(PredictionDismissal).all()] == [kept.id]

    def test_each_row_carries_what_the_dialog_needs(self, client, db):
        from bs4 import BeautifulSoup

        item = _due_item(db)

        for url in ("/api/predictions/optimized-list", "/api/predictions/restock-table"):
            soup = BeautifulSoup(client.get(url).text, "html.parser")
            row = soup.find(attrs={"data-dismiss-item": str(item.id)})
            assert row is not None, url
            assert row["data-dismiss-name"] == "Egg Nog"
            assert row.find("button", attrs={"data-dismiss-button": True}) is not None

    def test_the_page_has_the_dialog_with_three_periods(self, client):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(client.get("/restock").text, "html.parser")

        dialog = soup.find("dialog", id="dismiss-dialog")
        periods = [
            b["data-dismiss-period"] for b in dialog.find_all(attrs={"data-dismiss-period": True})
        ]
        assert periods == ["week", "month", "forever"]
