"""CM-08: a lesson a person removed stays removed.

``record_corrections`` deletes and re-writes a receipt's correction rows on
every save, so a removal that pointed at a row would be undone by the next
save. The decision is keyed on content instead, and is checked both when
corrections are written and when a prompt is built.
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from app.models import CorrectionOverride, OcrCorrection, Receipt, Store
from app.services.correction_keys import content_key
from app.services.correction_service import (
    get_correction_prompt,
    select_corrections,
    set_suppressed,
    suppressed_keys,
)


def _store(db, name="Costco"):
    store = db.query(Store).filter_by(name=name).first()
    if not store:
        store = Store(name=name)
        db.add(store)
        db.commit()
    return store


def _receipt(db, store, image_path="/data/uploads/a.jpg"):
    receipt = Receipt(status="completed", store_id=store.id, image_path=image_path)
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt


def _lesson(db, receipt, ai_value, approved_value, minutes_ago=0, field="name"):
    row = OcrCorrection(
        receipt_id=receipt.id,
        store_id=receipt.store_id,
        field=field,
        input_type="image",
        ai_value=ai_value,
        approved_value=approved_value,
        content_key=content_key(receipt.store_id, "image", field, ai_value, approved_value),
        created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _lines(block):
    return [line for line in block.splitlines() if line.startswith("- ")]


# ---------------------------------------------------------------------------
# Recording the decision
# ---------------------------------------------------------------------------


def test_suppressing_creates_an_override_carrying_the_lesson(db):
    receipt = _receipt(db, _store(db))
    row = _lesson(db, receipt, "MLK WHL GAL", "Whole Milk")

    override = set_suppressed(db, row)

    assert override.suppressed is True
    assert override.content_key == row.content_key
    assert override.ai_value == "MLK WHL GAL"
    assert override.approved_value == "Whole Milk"
    assert override.input_type == "image"
    assert override.field == "name"


def test_suppressing_twice_reuses_one_override(db):
    """content_key is unique, so a second decision updates rather than inserts."""
    receipt = _receipt(db, _store(db))
    row = _lesson(db, receipt, "MLK WHL GAL", "Whole Milk")

    set_suppressed(db, row)
    set_suppressed(db, row)

    assert db.query(CorrectionOverride).filter_by(content_key=row.content_key).count() == 1


def test_a_lesson_can_be_allowed_back(db):
    receipt = _receipt(db, _store(db))
    row = _lesson(db, receipt, "MLK WHL GAL", "Whole Milk")

    set_suppressed(db, row)
    assert row.content_key in suppressed_keys(db)

    set_suppressed(db, row, suppressed=False)
    assert row.content_key not in suppressed_keys(db)
    assert _lines(get_correction_prompt(db))


def test_a_correction_without_a_key_cannot_be_suppressed(db):
    receipt = _receipt(db, _store(db))
    row = OcrCorrection(
        receipt_id=receipt.id,
        store_id=receipt.store_id,
        field="name",
        input_type="image",
        ai_value="MLK",
        approved_value="Milk",
    )
    db.add(row)
    db.commit()

    with pytest.raises(ValueError):
        set_suppressed(db, row)


def test_suppressed_keys_lists_only_suppressed_ones(db):
    receipt = _receipt(db, _store(db))
    gone = _lesson(db, receipt, "MLK WHL GAL", "Whole Milk")
    kept = _lesson(db, receipt, "ORG SPNCH", "Organic Spinach", 5)

    set_suppressed(db, gone)
    set_suppressed(db, kept, suppressed=False)

    assert suppressed_keys(db) == {gone.content_key}


# ---------------------------------------------------------------------------
# Suppressed lessons stay out of prompts
# ---------------------------------------------------------------------------


def test_a_suppressed_lesson_is_not_in_the_block(db):
    receipt = _receipt(db, _store(db))
    gone = _lesson(db, receipt, "MLK WHL GAL", "Whole Milk")
    _lesson(db, receipt, "ORG SPNCH", "Organic Spinach", 5)

    set_suppressed(db, gone)
    lines = _lines(get_correction_prompt(db))

    assert len(lines) == 1
    assert "Whole Milk" not in "\n".join(lines)
    assert "Organic Spinach" in lines[0]


def test_an_existing_row_is_filtered_even_before_the_next_save(db):
    """The row stays in the table until its review is saved again."""
    receipt = _receipt(db, _store(db))
    gone = _lesson(db, receipt, "MLK WHL GAL", "Whole Milk")

    set_suppressed(db, gone)

    assert db.query(OcrCorrection).filter_by(id=gone.id).one_or_none() is not None
    rows, _ = select_corrections(db)
    assert rows == []


def test_suppressing_every_lesson_gives_an_empty_block(db):
    receipt = _receipt(db, _store(db))
    for i in range(3):
        set_suppressed(db, _lesson(db, receipt, f"AI {i}", f"Real {i}", i))

    assert get_correction_prompt(db) == ""


def test_a_suppressed_lesson_frees_its_slot(db):
    """The block fills to the limit from what is left, not short by the removals."""
    receipt = _receipt(db, _store(db))
    rows = [_lesson(db, receipt, f"AI {i}", f"Real {i}", i) for i in range(12)]

    set_suppressed(db, rows[0])
    set_suppressed(db, rows[1])

    assert len(_lines(get_correction_prompt(db))) == 10


def test_suppression_applies_to_its_own_lesson_only(db):
    """The same text at another store is a different lesson, so it stays."""
    costco = _store(db)
    safeway = _store(db, "Safeway")
    at_costco = _lesson(db, _receipt(db, costco), "MLK WHL GAL", "Whole Milk")
    _lesson(db, _receipt(db, safeway, "/data/uploads/s.jpg"), "MLK WHL GAL", "Whole Milk", 5)

    set_suppressed(db, at_costco)

    assert len(_lines(get_correction_prompt(db))) == 1
    assert "Safeway" in get_correction_prompt(db, store_name="Safeway", input_type="image")


def test_a_lookup_failure_returns_no_keys(db):
    """The read is caught where it happens, so no caller has to handle it."""
    with patch.object(db, "query", side_effect=RuntimeError("table is gone")):
        assert suppressed_keys(db) == set()


def test_a_lookup_failure_fails_open(db):
    """No keys means no suppression applied: the lesson is sent, not lost.

    Failing closed would drop every lesson from the prompt, or refuse the
    review save, because the override table could not be read.
    """
    receipt = _receipt(db, _store(db))
    row = _lesson(db, receipt, "MLK WHL GAL", "Whole Milk")
    set_suppressed(db, row)

    assert get_correction_prompt(db) == ""

    with patch("app.services.correction_service.suppressed_keys", return_value=set()):
        assert "Whole Milk" in get_correction_prompt(db)


# ---------------------------------------------------------------------------
# Re-saving a review does not bring it back
# ---------------------------------------------------------------------------


def _reviewed_receipt(db, image_path="/data/uploads/spinach.jpg"):
    store = _store(db)
    receipt = Receipt(
        store_id=store.id,
        purchase_date=datetime(2026, 7, 1),
        total_amount=3.99,
        status="completed",
        image_path=image_path,
        ocr_data=json.dumps({"items": [{"name": "ORG SPNCH", "final_price": 3.99, "quantity": 1}]}),
    )
    db.add(receipt)
    db.commit()
    return receipt


def _save_review(client, receipt_id):
    resp = client.post(
        f"/api/receipts/{receipt_id}/save-reviewed-items",
        json={
            "items": [
                {
                    "name": "Organic Spinach",
                    "base_price": 3.99,
                    "quantity": 1.0,
                    "discounts": [],
                    "fees": [],
                    "final_price": 3.99,
                }
            ],
            "store_name": "Costco",
        },
    )
    assert resp.status_code == 200 and resp.json()["success"]


def test_a_suppressed_lesson_is_not_re_recorded_on_a_re_save(client, db):
    receipt = _reviewed_receipt(db)
    _save_review(client, receipt.id)
    row = db.query(OcrCorrection).filter_by(receipt_id=receipt.id, field="name").one()

    set_suppressed(db, row)
    _save_review(client, receipt.id)
    db.expire_all()

    assert db.query(OcrCorrection).filter_by(receipt_id=receipt.id, field="name").count() == 0


def test_the_block_is_unchanged_by_a_re_save(client, db):
    """Suppress, save the review again, and the lesson is still absent."""
    receipt = _reviewed_receipt(db)
    _save_review(client, receipt.id)
    row = db.query(OcrCorrection).filter_by(receipt_id=receipt.id, field="name").one()
    set_suppressed(db, row)

    before = get_correction_prompt(db)
    _save_review(client, receipt.id)
    db.expire_all()

    assert get_correction_prompt(db) == before == ""


def test_an_unsuppressed_lesson_is_still_re_recorded(client, db):
    """The guard is specific: other corrections on the receipt are unaffected."""
    receipt = _reviewed_receipt(db)
    _save_review(client, receipt.id)
    first = db.query(OcrCorrection).filter_by(receipt_id=receipt.id, field="name").one()
    key = first.content_key

    _save_review(client, receipt.id)
    db.expire_all()
    again = db.query(OcrCorrection).filter_by(receipt_id=receipt.id, field="name").one()

    assert again.content_key == key


def test_allowing_a_lesson_back_lets_a_re_save_record_it(client, db):
    receipt = _reviewed_receipt(db)
    _save_review(client, receipt.id)
    row = db.query(OcrCorrection).filter_by(receipt_id=receipt.id, field="name").one()
    key = row.content_key

    set_suppressed(db, row)
    _save_review(client, receipt.id)
    db.expire_all()
    assert db.query(OcrCorrection).filter_by(content_key=key).count() == 0

    override = db.query(CorrectionOverride).filter_by(content_key=key).one()
    override.suppressed = False
    db.commit()
    _save_review(client, receipt.id)
    db.expire_all()

    assert db.query(OcrCorrection).filter_by(content_key=key).count() == 1


def test_the_override_outlives_the_correction_row(client, db):
    """The row is deleted by the re-save; the decision still names the lesson."""
    receipt = _reviewed_receipt(db)
    _save_review(client, receipt.id)
    row = db.query(OcrCorrection).filter_by(receipt_id=receipt.id, field="name").one()
    key = row.content_key
    set_suppressed(db, row)

    _save_review(client, receipt.id)
    db.expire_all()

    assert db.query(OcrCorrection).filter_by(content_key=key).count() == 0
    override = db.query(CorrectionOverride).filter_by(content_key=key).one()
    assert override.ai_value == "ORG SPNCH"
    assert override.approved_value == "Organic Spinach"
