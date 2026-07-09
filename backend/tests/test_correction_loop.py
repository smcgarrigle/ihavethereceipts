"""OCR feedback loop: corrections captured on review-save and injected as few-shot."""

import json
from datetime import datetime

from app.models import OcrCorrection, Receipt, Store
from app.services.correction_service import get_correction_prompt


def _seed_ai_receipt(db, store_name="Costco", ai_items=None):
    store = db.query(Store).filter_by(name=store_name).first()
    if not store:
        store = Store(name=store_name)
        db.add(store)
        db.commit()

    receipt = Receipt(
        store_id=store.id,
        purchase_date=datetime(2026, 7, 1),
        total_amount=20.0,
        status="completed",
        ocr_data=json.dumps({"items": ai_items or [], "store_name": store_name}),
    )
    db.add(receipt)
    db.commit()
    return receipt


def _save_review(client, receipt_id, items):
    return client.post(
        f"/api/receipts/{receipt_id}/save-reviewed-items",
        json={"items": items, "store_name": "Costco"},
    )


def _reviewed(name, price, qty=1.0):
    return {
        "name": name,
        "base_price": price,
        "quantity": qty,
        "discounts": [],
        "fees": [],
        "final_price": price,
    }


def test_name_correction_recorded(client, db):
    receipt = _seed_ai_receipt(
        db,
        ai_items=[
            {"name": "ORG SPNCH Qty 1 @ $3.99", "final_price": 3.99, "quantity": 1},
            {"name": "KS ALMOND BTR", "final_price": 11.49, "quantity": 1},
        ],
    )
    resp = _save_review(
        client,
        receipt.id,
        [_reviewed("Organic Spinach", 3.99), _reviewed("Kirkland Almond Butter", 11.49)],
    )
    assert resp.status_code == 200 and resp.json()["success"]

    rows = db.query(OcrCorrection).filter_by(receipt_id=receipt.id, field="name").all()
    assert len(rows) == 2
    fixes = {r.ai_value: r.approved_value for r in rows}
    assert fixes["ORG SPNCH Qty 1 @ $3.99"] == "Organic Spinach"
    assert fixes["KS ALMOND BTR"] == "Kirkland Almond Butter"


def test_missed_and_hallucinated_items_recorded(client, db):
    receipt = _seed_ai_receipt(
        db,
        ai_items=[
            {"name": "Bananas", "final_price": 1.99, "quantity": 1},
            {"name": "SUBTOTAL SAVINGS CARD", "final_price": 55.20, "quantity": 1},
        ],
    )
    resp = _save_review(
        client,
        receipt.id,
        [_reviewed("Bananas", 1.99), _reviewed("Rotisserie Chicken", 4.99)],
    )
    assert resp.json()["success"]

    fields = {r.field for r in db.query(OcrCorrection).filter_by(receipt_id=receipt.id)}
    assert "item_missed" in fields
    assert "item_hallucinated" in fields
    # Identical names must not be stored as a name correction
    assert db.query(OcrCorrection).filter_by(receipt_id=receipt.id, field="name").count() == 0


def test_resave_is_idempotent(client, db):
    receipt = _seed_ai_receipt(
        db, ai_items=[{"name": "MLK WHL GAL", "final_price": 4.29, "quantity": 1}]
    )
    for _ in range(2):
        resp = _save_review(client, receipt.id, [_reviewed("Whole Milk", 4.29)])
        assert resp.json()["success"]
    assert db.query(OcrCorrection).filter_by(receipt_id=receipt.id).count() == 1


def test_correction_prompt_prefers_store_scope(client, db):
    r1 = _seed_ai_receipt(db, "Costco", [{"name": "ORG SPNCH", "final_price": 3.99, "quantity": 1}])
    _save_review(client, r1.id, [_reviewed("Organic Spinach", 3.99)])

    block = get_correction_prompt(db, store_name="Costco")
    assert "LEARNED CORRECTIONS" in block and "Costco" in block
    assert '"ORG SPNCH" was corrected to "Organic Spinach"' in block

    # Unknown store falls back to global recents rather than returning nothing
    fallback = get_correction_prompt(db, store_name="Nonexistent Mart")
    assert "LEARNED CORRECTIONS" in fallback and "all stores" in fallback


def test_no_corrections_no_prompt_block(db):
    assert get_correction_prompt(db) == ""


def test_manual_receipts_record_nothing(client, db):
    receipt = _seed_ai_receipt(db, ai_items=[])  # no AI extraction
    resp = _save_review(client, receipt.id, [_reviewed("Anything", 5.00)])
    assert resp.json()["success"]
    assert db.query(OcrCorrection).filter_by(receipt_id=receipt.id).count() == 0
