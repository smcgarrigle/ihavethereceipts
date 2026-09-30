"""CM-22: a review fix replaces the lesson it contradicts.

Fixing CHIPS -> Potato Chips to CHIPS -> Corn Chips on a later review used to
leave both lessons in the prompt until the old one aged out, so the model was
given two answers for one text. The latest save now wins, as it does for store
names and for item-editor renames.
"""

import json
from types import SimpleNamespace

from app.models import CorrectionOverride, Item, OcrCorrection, Receipt, ReceiptItem, Store
from app.services import correction_service
from app.services.correction_service import (
    get_correction_prompt,
    record_corrections,
    record_rename_corrections,
    set_pinned,
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


def _review(db, store, read_saved, image_path="/data/uploads/a.jpg", receipt=None):
    """Save a review. ``read_saved`` is [(text the model read, name saved, price)]."""
    if receipt is None:
        receipt = Receipt(status="completed", store_id=store.id, image_path=image_path)
        db.add(receipt)
        db.commit()
    receipt.ocr_data = json.dumps(
        {
            "items": [
                {"name": read, "final_price": price, "quantity": 1} for read, _, price in read_saved
            ]
        }
    )
    db.commit()
    reviewed = [
        SimpleNamespace(name=saved, final_price=price, quantity=1) for _, saved, price in read_saved
    ]
    record_corrections(db, receipt, reviewed)
    db.commit()
    return receipt


def _lesson(db, receipt, ai_value):
    return (
        db.query(OcrCorrection)
        .filter_by(receipt_id=receipt.id, field="name", ai_value=ai_value)
        .one()
    )


def test_a_later_review_fix_removes_the_lesson_it_contradicts(db):
    costco = _store(db)
    first = _review(db, costco, [("CHIPS", "Potato Chips", 3.99)])
    old_key = _lesson(db, first, "CHIPS").content_key

    second = _review(db, costco, [("CHIPS", "Corn Chips", 3.99)])

    assert old_key in suppressed_keys(db)
    assert _lesson(db, second, "CHIPS").content_key not in suppressed_keys(db)
    block = get_correction_prompt(db, store_name="Costco", input_type="image")
    assert "'CHIPS' was corrected to 'Corn Chips'" in block
    assert "Potato Chips" not in block


def test_the_same_answer_in_different_case_is_not_a_contradiction(db):
    costco = _store(db)
    first = _review(db, costco, [("CHIPS", "Potato Chips", 3.99)])

    _review(db, costco, [("CHIPS", "potato chips", 3.99)])

    assert _lesson(db, first, "CHIPS").content_key not in suppressed_keys(db)


def test_the_model_text_matches_regardless_of_case(db):
    costco = _store(db)
    first = _review(db, costco, [("Chips", "Potato Chips", 3.99)])

    _review(db, costco, [("CHIPS", "Corn Chips", 3.99)])

    assert _lesson(db, first, "Chips").content_key in suppressed_keys(db)


def test_two_answers_on_one_receipt_are_both_kept(db):
    """Two deposit lines read as CRV are two lines, not a correction of a correction."""
    costco = _store(db)
    receipt = _review(
        db,
        costco,
        [("CRV", "CRV Container Single Under 24OZ", 0.05), ("CRV", "CRV Alcohol 6PK", 0.30)],
    )

    assert not suppressed_keys(db)
    assert db.query(OcrCorrection).filter_by(receipt_id=receipt.id, field="name").count() == 2


def test_saving_the_same_review_again_keeps_its_own_lesson(db):
    costco = _store(db)
    receipt = _review(db, costco, [("CHIPS", "Corn Chips", 3.99)])

    _review(db, costco, [("CHIPS", "Corn Chips", 3.99)], receipt=receipt)

    assert not suppressed_keys(db)


def test_another_stores_lesson_is_left_alone(db):
    costco, safeway = _store(db, "Costco"), _store(db, "Safeway")
    elsewhere = _review(db, safeway, [("CHIPS", "Potato Chips", 3.99)])

    _review(db, costco, [("CHIPS", "Corn Chips", 3.99)])

    assert _lesson(db, elsewhere, "CHIPS").content_key not in suppressed_keys(db)


def test_another_input_types_lesson_is_left_alone(db):
    costco = _store(db)
    pdf = _review(db, costco, [("CHIPS", "Potato Chips", 3.99)], image_path="/data/uploads/a.pdf")

    _review(db, costco, [("CHIPS", "Corn Chips", 3.99)])

    assert _lesson(db, pdf, "CHIPS").content_key not in suppressed_keys(db)


def test_price_lessons_are_never_compared(db):
    """4.39 -> 4.59 on one item says nothing about 4.39 -> 3.99 on another."""
    costco = _store(db)
    first = _review(db, costco, [("MLK", "MLK", 4.59)])
    first.ocr_data = json.dumps({"items": [{"name": "MLK", "final_price": 4.39, "quantity": 1}]})
    db.commit()
    record_corrections(db, first, [SimpleNamespace(name="MLK", final_price=4.59, quantity=1)])
    db.commit()
    price = db.query(OcrCorrection).filter_by(receipt_id=first.id, field="price").one()

    second = Receipt(status="completed", store_id=costco.id, image_path="/data/uploads/b.jpg")
    db.add(second)
    db.commit()
    second.ocr_data = json.dumps({"items": [{"name": "EGG", "final_price": 4.39, "quantity": 1}]})
    db.commit()
    record_corrections(db, second, [SimpleNamespace(name="EGG", final_price=3.99, quantity=1)])
    db.commit()

    assert price.content_key not in suppressed_keys(db)


def test_a_rename_lesson_contradicted_by_a_later_review_is_removed(db):
    costco = _store(db)
    chips = Item(name="Chips", normalized_name="chips")
    db.add(chips)
    db.commit()
    receipt = Receipt(
        status="completed",
        store_id=costco.id,
        image_path="/data/uploads/a.jpg",
        ocr_data=json.dumps({"items": [{"name": "CHIPS", "final_price": 3.99, "quantity": 1}]}),
    )
    db.add(receipt)
    db.commit()
    db.add(ReceiptItem(receipt_id=receipt.id, item_id=chips.id, price=3.99, quantity=1))
    db.commit()
    chips.name = "Potato Chips"
    db.commit()
    record_rename_corrections(db, chips, "Chips", "Potato Chips")
    renamed = db.query(OcrCorrection).filter_by(source="item_editor").one()

    _review(db, costco, [("CHIPS", "Corn Chips", 3.99)])

    assert renamed.content_key in suppressed_keys(db)


def test_re_saving_a_receipt_replaces_a_rename_lesson_on_that_receipt(db):
    """Rename lessons survive a review re-save, so they can contradict it."""
    costco = _store(db)
    chips = Item(name="Chips", normalized_name="chips")
    db.add(chips)
    db.commit()
    receipt = _review(db, costco, [("CHIPS", "Chips", 3.99)])
    db.add(ReceiptItem(receipt_id=receipt.id, item_id=chips.id, price=3.99, quantity=1))
    db.commit()
    chips.name = "Potato Chips"
    db.commit()
    record_rename_corrections(db, chips, "Chips", "Potato Chips")
    renamed = db.query(OcrCorrection).filter_by(source="item_editor").one()

    _review(db, costco, [("CHIPS", "Corn Chips", 3.99)], receipt=receipt)

    assert renamed.content_key in suppressed_keys(db)


def test_a_lesson_a_person_restored_is_not_removed_again(db):
    costco = _store(db)
    first = _review(db, costco, [("CHIPS", "Potato Chips", 3.99)])
    second = _review(db, costco, [("CHIPS", "Corn Chips", 3.99)])
    old = _lesson(db, first, "CHIPS")
    set_suppressed(db, old, suppressed=False)

    _review(db, costco, [("CHIPS", "Corn Chips", 3.99)], receipt=second)

    assert old.content_key not in suppressed_keys(db)


def test_a_pinned_lesson_is_not_removed(db):
    costco = _store(db)
    first = _review(db, costco, [("CHIPS", "Potato Chips", 3.99)])
    old = _lesson(db, first, "CHIPS")
    set_pinned(db, old)

    _review(db, costco, [("CHIPS", "Corn Chips", 3.99)])

    assert old.content_key not in suppressed_keys(db)


def test_a_rename_leaves_a_lesson_a_person_pinned(db):
    """The same guard on the item-editor path (CM-20)."""
    costco = _store(db)
    chips = Item(name="Chips", normalized_name="chips")
    db.add(chips)
    db.commit()
    receipt = _review(db, costco, [("CHP", "Chips", 3.99)])
    db.add(ReceiptItem(receipt_id=receipt.id, item_id=chips.id, price=3.99, quantity=1))
    db.commit()
    pinned = _lesson(db, receipt, "CHP")
    set_pinned(db, pinned)

    chips.name = "Potato Chips"
    db.commit()
    result = record_rename_corrections(db, chips, "Chips", "Potato Chips")

    assert result["superseded"] == 0
    assert pinned.content_key not in suppressed_keys(db)


def test_a_failure_tidying_old_lessons_keeps_the_new_ones(db, monkeypatch):
    costco = _store(db)
    _review(db, costco, [("CHIPS", "Potato Chips", 3.99)])

    def broken(*_args, **_kwargs):
        raise RuntimeError("override table gone")

    monkeypatch.setattr(correction_service, "_supersede_contradicted", broken)
    receipt = Receipt(status="completed", store_id=costco.id, image_path="/data/uploads/b.jpg")
    db.add(receipt)
    db.commit()
    receipt.ocr_data = json.dumps(
        {"items": [{"name": "CHIPS", "final_price": 3.99, "quantity": 1}]}
    )
    db.commit()

    recorded = record_corrections(
        db, receipt, [SimpleNamespace(name="Corn Chips", final_price=3.99, quantity=1)]
    )
    db.commit()

    assert recorded == 1
    assert _lesson(db, receipt, "CHIPS").approved_value == "Corn Chips"
    assert db.query(CorrectionOverride).count() == 0
