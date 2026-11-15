"""Container deposit lines stay out of corrections.

A deposit (California Redemption Value, "CA REDEMP VA", "Bottle Deposit Fee")
is a fee printed on almost every receipt with a drink on it. Its corrections
repeat on every receipt and crowd out the ones about products, so they are not
recorded, not sent in a prompt, and not listed on the corrections page. Rows
stored before this rule are filtered where they are read.
"""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models import OcrCorrection, Receipt, Store
from app.services.correction_keys import content_key
from app.services.correction_service import (
    is_deposit_correction,
    is_deposit_line,
    list_corrections,
    record_corrections,
    select_corrections,
)


def _receipt(db, ai_items=None):
    store = db.query(Store).filter_by(name="Costco").first()
    if not store:
        store = Store(name="Costco")
        db.add(store)
        db.commit()
    receipt = Receipt(
        status="completed",
        store_id=store.id,
        image_path="/data/uploads/a.jpg",
        ocr_data=json.dumps({"items": ai_items}) if ai_items is not None else None,
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt


def _stored(db, receipt, field, ai_value, approved_value, item_context=None, minutes_ago=0):
    row = OcrCorrection(
        receipt_id=receipt.id,
        store_id=receipt.store_id,
        field=field,
        input_type="image",
        ai_value=ai_value,
        approved_value=approved_value,
        item_context=item_context,
        content_key=content_key(receipt.store_id, "image", field, ai_value, approved_value),
        created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )
    db.add(row)
    db.commit()
    return row


def _reviewed(name, price, quantity=1.0):
    return SimpleNamespace(name=name, final_price=price, quantity=quantity)


@pytest.mark.parametrize(
    "name",
    [
        "CRV",
        "CA REDEMP VA",
        "California Redemption Value",
        "CRV CRV Container Single Under 24OZ",
        "T.CRV UNDER 24oz",
        "Bottle Deposit Fee",
        "REFRIGERATED BTL DEPOSIT",
    ],
)
def test_deposit_names_are_recognised(name):
    assert is_deposit_line(name)


@pytest.mark.parametrize("name", ["Whole Milk", "Scrven Bread", "Coffee", None, 3])
def test_other_names_are_not(name):
    assert not is_deposit_line(name)


def test_a_price_correction_is_judged_by_the_line_it_names():
    assert is_deposit_correction("price", "0.60", "0.00", "CRV")
    assert not is_deposit_correction("price", "0.60", "0.00", "Whole Milk")


def test_a_review_records_nothing_for_deposit_lines(db):
    receipt = _receipt(
        db,
        [
            {"name": "MLK WHL GAL", "final_price": 4.0, "quantity": 1},
            {"name": "CRV CRV Container Single Under 24OZ", "final_price": 0.6, "quantity": 1},
        ],
    )
    reviewed = [
        _reviewed("Whole Milk Gallon", 4.0),
        _reviewed("CRV", 0.05),
        _reviewed("CA REDEMP VA", 0.1),
    ]

    record_corrections(db, receipt, reviewed)
    db.commit()

    rows = db.query(OcrCorrection).all()
    assert rows, "the product correction should still be recorded"
    for row in rows:
        assert not is_deposit_correction(
            row.field, row.ai_value, row.approved_value, row.item_context
        )


def test_stored_deposit_rows_are_not_sent_in_a_prompt(db):
    receipt = _receipt(db)
    _stored(db, receipt, "item_missed", None, "CRV")
    _stored(db, receipt, "price", "0.60", "0.00", item_context="CRV")
    _stored(db, receipt, "name", "MLK WHL GAL", "Whole Milk", minutes_ago=5)

    rows, _ = select_corrections(db, "Costco", input_type="image")

    assert [(r.field, r.approved_value) for r in rows] == [("name", "Whole Milk")]


def test_stored_deposit_rows_are_not_listed(db):
    receipt = _receipt(db)
    _stored(db, receipt, "item_missed", None, "CRV")
    _stored(db, receipt, "item_hallucinated", "Bottle Deposit Tax:", None)
    _stored(db, receipt, "name", "MLK WHL GAL", "Whole Milk")

    listed = list_corrections(db)

    assert [(r["field"], r["approved_value"]) for r in listed] == [("name", "Whole Milk")]
