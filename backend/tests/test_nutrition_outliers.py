"""Percentile-based outlier winsorization for nutrition trend charts."""

from datetime import datetime

from app.api import trends_nutrition
from app.api.trends_nutrition import (
    DEFAULT_PERCENTILE,
    MIN_WINSORIZE_POINTS,
    _get_nutrition_data,
    _get_outlier_percentile,
    _winsorize_rows,
)
from app.models import Item, Receipt, ReceiptItem, Store


def _row(sodium=0.0, fat=0.0, saturated_fat=0.0, sugar=0.0, protein=0.0, week="2026-22"):
    return {
        "week": week,
        "item_name": "Test Item",
        "fat": fat,
        "saturated_fat": saturated_fat,
        "sugar": sugar,
        "protein": protein,
        "sodium": sodium,
    }


def _seed_purchase(db, item_name, nutrients=None, weight=None, unit=None, qty=1.0):
    store = db.query(Store).filter_by(name="Test Store").first()
    if not store:
        store = Store(name="Test Store")
        db.add(store)
        db.commit()

    item = Item(name=item_name, nutrients=nutrients)
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


# ---------------------------------------------------------------------------
# _winsorize_rows (pure)
# ---------------------------------------------------------------------------


def test_winsorize_caps_outlier_at_floor_rank_percentile():
    rows = [_row(sodium=100.0) for _ in range(9)] + [_row(sodium=500000.0)]
    rows, meta = _winsorize_rows(rows, 95)

    # Floor-rank p95 of 10 points, clamped to second-largest: rank 9 → 100.0
    assert max(r["sodium"] for r in rows) == 100.0
    assert meta["enabled"] is True
    assert meta["percentile"] == 95
    assert meta["capped_points"] == 1
    assert meta["per_nutrient"]["sodium"] == {"cap": 100.0, "capped": 1}
    # Other nutrients were all zero — untouched, no meta entries
    assert set(meta["per_nutrient"]) == {"sodium"}


def test_winsorize_small_n_guard_skips_sparse_nutrients():
    rows = [_row(sodium=100.0) for _ in range(MIN_WINSORIZE_POINTS - 2)] + [_row(sodium=500000.0)]
    rows, meta = _winsorize_rows(rows, 95)
    assert max(r["sodium"] for r in rows) == 500000.0
    assert meta["capped_points"] == 0


def test_winsorize_all_equal_values_unchanged():
    rows = [_row(sodium=250.0) for _ in range(10)]
    rows, meta = _winsorize_rows(rows, 90)
    assert all(r["sodium"] == 250.0 for r in rows)
    assert meta["capped_points"] == 0
    assert meta["per_nutrient"] == {}


def test_winsorize_empty_rows():
    rows, meta = _winsorize_rows([], 95)
    assert rows == []
    assert meta["enabled"] is True
    assert meta["capped_points"] == 0


def test_winsorize_off_is_passthrough():
    rows = [_row(sodium=100.0) for _ in range(9)] + [_row(sodium=500000.0)]
    rows, meta = _winsorize_rows(rows, 0)
    assert max(r["sodium"] for r in rows) == 500000.0
    assert meta["enabled"] is False
    assert meta["capped_points"] == 0


def test_winsorize_nutrients_capped_independently():
    rows = [_row(sodium=100.0, protein=20.0) for _ in range(9)] + [
        _row(sodium=500000.0, protein=20.0)
    ]
    rows, meta = _winsorize_rows(rows, 95)
    # Sodium's outlier is capped, while protein (all equal) is untouched —
    # each nutrient is judged only against its own distribution
    assert "sodium" in meta["per_nutrient"]
    assert "protein" not in meta["per_nutrient"]
    assert all(r["protein"] == 20.0 for r in rows)


# ---------------------------------------------------------------------------
# _get_outlier_percentile (flag parsing)
# ---------------------------------------------------------------------------


def test_outlier_percentile_flag_parsing(monkeypatch):
    from app.api import settings_router

    cases = [
        ({}, DEFAULT_PERCENTILE),  # absent → default
        ({"nutrition_outlier_percentile": 0}, 0),  # off
        ({"nutrition_outlier_percentile": 90}, 90),
        ({"nutrition_outlier_percentile": "90"}, 90),  # string coerced
        ({"nutrition_outlier_percentile": 73}, DEFAULT_PERCENTILE),  # not allowed
        ({"nutrition_outlier_percentile": "abc"}, DEFAULT_PERCENTILE),
        ({"nutrition_outlier_percentile": None}, DEFAULT_PERCENTILE),
    ]
    for flags, expected in cases:
        monkeypatch.setattr(settings_router, "_load_feature_flags", lambda flags=flags: flags)
        assert _get_outlier_percentile() == expected, flags


# ---------------------------------------------------------------------------
# Integration through _get_nutrition_data
# ---------------------------------------------------------------------------


def _seed_salt_bomb_scenario(db):
    # 8 modest items so sodium clears the small-N guard, plus one 3lb salt box
    for i in range(8):
        _seed_purchase(db, f"Soup {i}", nutrients={"sodium_100g": 0.3}, weight=400.0, unit="g")
    _seed_purchase(db, "SALT 3LB", nutrients={"sodium_100g": 38.0}, weight=3.0, unit="lb")


def test_get_nutrition_data_caps_salt_bomb(db, monkeypatch):
    _seed_salt_bomb_scenario(db)
    monkeypatch.setattr(trends_nutrition, "_get_outlier_percentile", lambda: 95)

    rows, meta = _get_nutrition_data("all", db)
    assert len(rows) == 9
    # Cap is an observed value from the normal purchases (400g * 0.3g/100g * 1000 = 1200mg)
    assert max(r["sodium"] for r in rows) == 1200.0
    assert meta["capped_points"] == 1
    assert meta["per_nutrient"]["sodium"]["cap"] == 1200.0


def test_get_nutrition_data_off_returns_raw(db, monkeypatch):
    _seed_salt_bomb_scenario(db)
    monkeypatch.setattr(trends_nutrition, "_get_outlier_percentile", lambda: 0)

    rows, meta = _get_nutrition_data("all", db)
    salt_mg = 3.0 * 453.592 * 38.0 / 100.0 * 1000.0
    assert abs(max(r["sodium"] for r in rows) - salt_mg) < 1.0
    assert meta["enabled"] is False


def test_all_charts_fragment_delivers_normalization_meta(client, db, monkeypatch):
    _seed_salt_bomb_scenario(db)
    monkeypatch.setattr(trends_nutrition, "_get_outlier_percentile", lambda: 95)

    resp = client.get("/api/trends/fragment/all-charts?time_range=all")
    assert resp.status_code == 200
    assert "nutrition_normalization" in resp.text
    assert "capped_points" in resp.text


# ---------------------------------------------------------------------------
# Settings endpoint
# ---------------------------------------------------------------------------


def test_set_outlier_percentile_persists(client, tmp_path, monkeypatch):
    from app.api import settings_router

    flags_path = tmp_path / "feature_flags.json"
    monkeypatch.setattr(settings_router, "FEATURE_FLAGS_PATH", flags_path)

    resp = client.post("/settings/flags/nutrition-outlier-percentile?percentile=90")
    assert resp.status_code == 200
    assert resp.json() == {"success": True, "nutrition_outlier_percentile": 90}

    flags = client.get("/settings/flags").json()
    assert flags["nutrition_outlier_percentile"] == 90


def test_set_outlier_percentile_rejects_invalid(client, tmp_path, monkeypatch):
    from app.api import settings_router

    monkeypatch.setattr(settings_router, "FEATURE_FLAGS_PATH", tmp_path / "feature_flags.json")

    resp = client.post("/settings/flags/nutrition-outlier-percentile?percentile=73")
    assert resp.status_code == 422
    assert resp.json()["success"] is False


def test_set_outlier_percentile_zero_disables(client, tmp_path, monkeypatch):
    from app.api import settings_router

    monkeypatch.setattr(settings_router, "FEATURE_FLAGS_PATH", tmp_path / "feature_flags.json")

    resp = client.post("/settings/flags/nutrition-outlier-percentile?percentile=0")
    assert resp.status_code == 200
    assert resp.json()["nutrition_outlier_percentile"] == 0


def test_settings_page_renders_outlier_select(client):
    from bs4 import BeautifulSoup

    resp = client.get("/settings")
    assert resp.status_code == 200
    soup = BeautifulSoup(resp.text, "html.parser")
    assert soup.find(id="nutrition-outlier-select") is not None
