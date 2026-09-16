"""CM-04: price lessons carry the quantity, and column mix-ups are not lessons.

"price was corrected from 4.34 to 8.68" is what a line of two units looks like
when the model read the per-unit column instead of the line total. Recorded as a
lesson, it teaches the model to double prices. Nine of the 71 price corrections
in the live log are that mix-up, six of them from pasted tables.
"""

import json
from datetime import datetime

import pytest

from app.models import OcrCorrection, Receipt, Store
from app.services.correction_service import _is_quantity_mixup, get_correction_prompt


@pytest.fixture
def store(db):
    store = Store(name="Iherb")
    db.add(store)
    db.commit()
    db.refresh(store)
    return store


def _receipt(db, store, ai_items):
    receipt = Receipt(
        store_id=store.id,
        purchase_date=datetime(2026, 7, 1),
        total_amount=20.0,
        status="completed",
        image_path="/data/uploads/a.jpg",
        ocr_data=json.dumps({"items": ai_items}),
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt


def _save(client, receipt_id, name, final_price, quantity, store_name="Iherb"):
    resp = client.post(
        f"/api/receipts/{receipt_id}/save-reviewed-items",
        json={
            "items": [
                {
                    "name": name,
                    "base_price": final_price,
                    "quantity": quantity,
                    "discounts": [],
                    "fees": [],
                    "final_price": final_price,
                }
            ],
            "store_name": store_name,
        },
    )
    assert resp.status_code == 200 and resp.json()["success"]


@pytest.mark.parametrize(
    ("model_value", "saved_value", "quantity", "expected"),
    [
        (4.34, 8.68, 2, True),  # exactly double
        (3.69, 7.39, 2, True),  # a cent out: 3.695 a unit, rounded on the way in
        (9.29, 18.59, 2, True),  # the same, receipt #461
        (0.05, 0.20, 3, False),  # five cents out at quantity 3: a real correction
        (6.91, 5.80, 1, False),  # single unit, so nothing to mix up
        (2.50, 5.00, None, False),  # quantity unknown
        (10.99, 0.00, 2, False),  # reclassified to zero, not a mix-up
    ],
)
def test_quantity_mixup_rule(model_value, saved_value, quantity, expected):
    assert _is_quantity_mixup(model_value, saved_value, quantity) is expected


def test_a_column_mixup_is_not_recorded(db, client, store):
    """The model read 4.34 a unit; the line of two came to 8.68."""
    receipt = _receipt(db, store, [{"name": "Barry's Tea", "final_price": 4.34, "quantity": 2}])

    _save(client, receipt.id, "Barry's Tea", 8.68, 2)

    assert db.query(OcrCorrection).filter_by(receipt_id=receipt.id, field="price").count() == 0


def test_a_rounded_per_unit_price_is_still_a_mixup(db, client, store):
    """3.695 a unit prints as 3.69, and two of them come to 7.39, not 7.38."""
    receipt = _receipt(db, store, [{"name": "Rice Snaps", "final_price": 3.69, "quantity": 2}])

    _save(client, receipt.id, "Rice Snaps", 7.39, 2)

    assert db.query(OcrCorrection).filter_by(receipt_id=receipt.id, field="price").count() == 0


def test_a_real_misreading_is_still_recorded_with_its_quantity(db, client, store):
    receipt = _receipt(db, store, [{"name": "Olives", "final_price": 5.51, "quantity": 2}])

    _save(client, receipt.id, "Olives", 4.59, 2)

    row = db.query(OcrCorrection).filter_by(receipt_id=receipt.id, field="price").one()
    assert row.ai_value == "5.51" and row.approved_value == "4.59"
    assert row.quantity == 2


def test_the_prompt_says_how_many_the_line_held(db, client, store):
    receipt = _receipt(db, store, [{"name": "Olives", "final_price": 5.51, "quantity": 3}])
    _save(client, receipt.id, "Olives", 4.59, 3)

    block = get_correction_prompt(db)

    assert "(a line of 3)" in block
    assert "price for 'Olives' (a line of 3) was corrected from '5.51' to '4.59'." in block


def test_a_single_unit_line_says_nothing_about_quantity(db, client, store):
    receipt = _receipt(db, store, [{"name": "Olives", "final_price": 5.51, "quantity": 1}])
    _save(client, receipt.id, "Olives", 4.59, 1)

    block = get_correction_prompt(db)

    assert "a line of" not in block
    assert "price for 'Olives' was corrected from '5.51' to '4.59'." in block


def test_rows_without_a_quantity_render_as_before(db, store):
    """Corrections written before the column existed carry no quantity."""
    receipt = _receipt(db, store, [])
    db.add(
        OcrCorrection(
            receipt_id=receipt.id,
            store_id=store.id,
            field="price",
            input_type="image",
            item_context="Muesli",
            ai_value="9.29",
            approved_value="18.59",
        )
    )
    db.commit()

    block = get_correction_prompt(db)

    assert "price for 'Muesli' was corrected from '9.29' to '18.59'." in block
    assert "a line of" not in block
