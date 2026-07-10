"""Phase 1 nutrition remediation: overrides, package-size fallback, coverage."""

from datetime import datetime

from app.api.trends_nutrition import _get_raw_nutrition_data, get_nutrition_coverage
from app.models import Item, Receipt, ReceiptItem, Store
from app.services.nutrition_utils import resolve_purchase_grams


def _seed_purchase(db, item_name, nutrients=None, custom=None, weight=None, unit=None, qty=1.0):
    store = db.query(Store).filter_by(name="Test Store").first()
    if not store:
        store = Store(name="Test Store")
        db.add(store)
        db.commit()

    item = Item(name=item_name, nutrients=nutrients, custom_nutrients=custom)
    db.add(item)
    db.commit()

    receipt = Receipt(
        store_id=store.id, purchase_date=datetime(2026, 6, 1), total_amount=10.0, status="completed"
    )
    db.add(receipt)
    db.commit()

    ri = ReceiptItem(
        receipt_id=receipt.id,
        item_id=item.id,
        quantity=qty,
        price=10.0,
        weight=weight,
        unit_type=unit,
    )
    db.add(ri)
    db.commit()
    return item, ri


def test_custom_nutrients_override_persists(client, db):
    item, _ = _seed_purchase(db, "Greek Yogurt", nutrients={"proteins_100g": 9.0})

    resp = client.put(
        f"/api/items/{item.id}/nutrition",
        json={"custom_nutrients": {"proteins_100g": 12.5, "sugars_100g": 4.0}},
    )
    assert resp.status_code == 200
    assert resp.json()["effective"]["proteins_100g"] == 12.5

    # Re-read from the DB to prove the JSON column change was actually flushed
    db.expire_all()
    fresh = db.query(Item).filter(Item.id == item.id).one()
    assert fresh.custom_nutrients == {"proteins_100g": 12.5, "sugars_100g": 4.0}
    assert fresh.effective_nutrients["proteins_100g"] == 12.5
    assert fresh.effective_nutrients["sugars_100g"] == 4.0


def test_custom_nutrients_blank_value_removes_key(client, db):
    item, _ = _seed_purchase(db, "Oat Milk", custom={"fat_100g": 3.0, "sugars_100g": 7.0})

    resp = client.put(
        f"/api/items/{item.id}/nutrition",
        json={"custom_nutrients": {"sugars_100g": ""}},
    )
    assert resp.status_code == 200

    db.expire_all()
    fresh = db.query(Item).filter(Item.id == item.id).one()
    assert fresh.custom_nutrients == {"fat_100g": 3.0}


def test_package_size_fallback_resolves_grams(db):
    # Discrete item: no weight on the line, size only in the name
    _, ri = _seed_purchase(db, "PEANUT BUTTER 16OZ", nutrients={"fat_100g": 50.0}, qty=2.0)
    grams = resolve_purchase_grams(ri)
    assert grams is not None
    assert abs(grams - 2 * 16 * 28.3495) < 0.1

    # No weight and no size in the name -> still None
    _, ri2 = _seed_purchase(db, "Mystery Snack", nutrients={"fat_100g": 1.0})
    assert resolve_purchase_grams(ri2) is None


def test_trends_includes_discrete_items_via_package_size(db):
    _seed_purchase(db, "GRANOLA 12OZ", nutrients={"proteins_100g": 10.0}, qty=1.0)
    records = _get_raw_nutrition_data("all", db)
    assert len(records) == 1
    expected_protein = 12 * 28.3495 / 100.0 * 10.0
    assert abs(records[0]["protein"] - expected_protein) < 0.1


def test_trends_includes_custom_only_items(db):
    # Item with no canonical nutrients but a manual override must appear
    _seed_purchase(db, "Homemade Bread", custom={"proteins_100g": 8.0}, weight=500.0, unit="g")
    records = _get_raw_nutrition_data("all", db)
    assert len(records) == 1
    assert abs(records[0]["protein"] - 40.0) < 0.01


def test_nutrition_coverage_math(db):
    _seed_purchase(db, "Covered Item 16OZ", nutrients={"fat_100g": 1.0})
    _seed_purchase(db, "Uncovered Item")
    coverage = get_nutrition_coverage("all", db)
    assert coverage["total_items"] == 2
    assert coverage["covered_items"] == 1
    assert coverage["spend_pct"] == 50.0


def test_all_charts_fragment_delivers_coverage(client, db):
    _seed_purchase(db, "Milk 32OZ", nutrients={"fat_100g": 3.5})
    resp = client.get("/api/trends/fragment/all-charts?time_range=all")
    assert resp.status_code == 200
    assert "nutrition_coverage" in resp.text
    assert "spend_pct" in resp.text
