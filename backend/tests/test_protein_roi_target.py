"""Protein ROI target ($/g) — configurable threshold behind the Trends BI dashboard."""

from datetime import datetime, timedelta

from app.models import Item, Receipt, ReceiptItem, Store


def _seed_protein_purchase(db, item_name, proteins_100g, price, weight_g=100.0):
    store = db.query(Store).filter_by(name="Test Store").first()
    if not store:
        store = Store(name="Test Store")
        db.add(store)
        db.commit()

    item = Item(name=item_name, nutrients={"proteins_100g": proteins_100g})
    db.add(item)
    db.commit()

    receipt = Receipt(
        store_id=store.id,
        purchase_date=datetime.utcnow() - timedelta(days=1),
        total_amount=price,
        status="completed",
    )
    db.add(receipt)
    db.commit()

    ri = ReceiptItem(
        receipt_id=receipt.id,
        item_id=item.id,
        quantity=1.0,
        price=price,
        weight=weight_g,
        unit_type="g",
    )
    db.add(ri)
    db.commit()
    return item, ri


def test_bi_dashboard_defaults_protein_roi_target(client, db, monkeypatch):
    from app.api import settings_router

    monkeypatch.setattr(settings_router, "_load_feature_flags", lambda: {})

    _seed_protein_purchase(db, "Chicken Breast", proteins_100g=30.0, price=3.0, weight_g=500.0)
    resp = client.get("/api/analytics/bi-dashboard")
    assert resp.status_code == 200
    assert resp.json()["protein_roi_target"] == 0.20


def test_bi_dashboard_reflects_custom_protein_roi_target(client, db, monkeypatch):
    from app.api import settings_router

    monkeypatch.setattr(
        settings_router, "_load_feature_flags", lambda: {"protein_roi_target": 0.35}
    )

    _seed_protein_purchase(db, "Protein Powder", proteins_100g=80.0, price=20.0, weight_g=500.0)
    resp = client.get("/api/analytics/bi-dashboard")
    assert resp.status_code == 200
    assert resp.json()["protein_roi_target"] == 0.35


def test_set_protein_roi_target_persists(client, tmp_path, monkeypatch):
    from app.api import settings_router

    monkeypatch.setattr(settings_router, "FEATURE_FLAGS_PATH", tmp_path / "feature_flags.json")

    resp = client.post("/settings/flags/protein-roi-target?target=0.30")
    assert resp.status_code == 200
    assert resp.json() == {"success": True, "protein_roi_target": 0.30}

    flags = client.get("/settings/flags").json()
    assert flags["protein_roi_target"] == 0.30


def test_set_protein_roi_target_rejects_out_of_range(client, tmp_path, monkeypatch):
    from app.api import settings_router

    monkeypatch.setattr(settings_router, "FEATURE_FLAGS_PATH", tmp_path / "feature_flags.json")

    for bad in (0.0, -1.0, 5.01, 100.0):
        resp = client.post(f"/settings/flags/protein-roi-target?target={bad}")
        assert resp.status_code == 422, bad
        assert resp.json()["success"] is False


def test_set_protein_roi_target_rounds_to_cents(client, tmp_path, monkeypatch):
    from app.api import settings_router

    monkeypatch.setattr(settings_router, "FEATURE_FLAGS_PATH", tmp_path / "feature_flags.json")

    resp = client.post("/settings/flags/protein-roi-target?target=0.256")
    assert resp.status_code == 200
    assert resp.json()["protein_roi_target"] == 0.26


def test_settings_page_renders_protein_roi_target_input(client):
    from bs4 import BeautifulSoup

    resp = client.get("/settings")
    assert resp.status_code == 200
    soup = BeautifulSoup(resp.text, "html.parser")
    assert soup.find(id="protein-roi-target-input") is not None
