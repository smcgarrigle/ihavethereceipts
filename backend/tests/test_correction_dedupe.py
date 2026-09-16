"""CM-03: one slot per lesson, not one slot per row.

The block held the newest rows, so a lesson recorded on several receipts took
several of the ten slots. On the live log, 433 corrections describe 342
distinct lessons, and the newest rows of a class repeat themselves.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.models import OcrCorrection, Receipt, Store
from app.services.correction_keys import content_key
from app.services.correction_service import get_correction_prompt


@pytest.fixture
def store(db):
    store = Store(name="Costco")
    db.add(store)
    db.commit()
    db.refresh(store)
    return store


@pytest.fixture
def receipt(db, store):
    receipt = Receipt(store_id=store.id, status="completed", image_path="/data/uploads/a.jpg")
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt


def _add(db, receipt, ai_value, approved_value, minutes_ago, with_key=True, field="name"):
    """One correction, aged so ordering is deterministic."""
    row = OcrCorrection(
        receipt_id=receipt.id,
        store_id=receipt.store_id,
        field=field,
        input_type="image",
        ai_value=ai_value,
        approved_value=approved_value,
        created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )
    if with_key:
        row.content_key = content_key(receipt.store_id, "image", field, ai_value, approved_value)
    db.add(row)
    db.commit()
    return row


def _lines(block):
    return [line for line in block.splitlines() if line.startswith("- ")]


def test_a_repeated_lesson_takes_one_slot(db, receipt):
    for minutes in range(12):
        _add(db, receipt, "MLK WHL GAL", "Whole Milk", minutes)
    _add(db, receipt, "ORG SPNCH", "Organic Spinach", 20)

    lines = _lines(get_correction_prompt(db))

    assert len(lines) == 2
    assert sum("Whole Milk" in line for line in lines) == 1


def test_the_block_still_fills_up_when_rows_repeat(db, receipt):
    """Ten distinct lessons, each recorded twice, must still fill ten slots."""
    for i in range(10):
        _add(db, receipt, f"AI NAME {i}", f"Real Name {i}", i * 2)
        _add(db, receipt, f"AI NAME {i}", f"Real Name {i}", i * 2 + 1)

    lines = _lines(get_correction_prompt(db))

    assert len(lines) == 10
    assert len(set(lines)) == 10


def test_no_line_appears_twice(db, receipt):
    for minutes in range(6):
        _add(db, receipt, "MLK WHL GAL", "Whole Milk", minutes)
        _add(db, receipt, "ORG SPNCH", "Organic Spinach", minutes + 30)

    lines = _lines(get_correction_prompt(db))

    assert lines == list(dict.fromkeys(lines))


def test_rows_without_a_stored_key_still_collapse(db, receipt):
    """Rows predating the key column are matched on their values instead."""
    for minutes in range(4):
        _add(db, receipt, "MLK WHL GAL", "Whole Milk", minutes, with_key=False)

    assert len(_lines(get_correction_prompt(db))) == 1


def test_surrounding_space_does_not_make_a_second_lesson(db, receipt):
    _add(db, receipt, "MLK WHL GAL", "Whole Milk", 1, with_key=False)
    _add(db, receipt, "  MLK WHL GAL ", "Whole Milk ", 2, with_key=False)

    assert len(_lines(get_correction_prompt(db))) == 1


def test_the_same_text_at_another_store_is_a_different_lesson(db, receipt):
    other = Store(name="Safeway")
    db.add(other)
    db.commit()
    other_receipt = Receipt(store_id=other.id, status="completed", image_path="/data/uploads/b.jpg")
    db.add(other_receipt)
    db.commit()

    _add(db, receipt, "MLK WHL GAL", "Whole Milk", 1)
    _add(db, other_receipt, "MLK WHL GAL", "Whole Milk", 2)

    assert len(_lines(get_correction_prompt(db))) == 2


def test_a_different_field_on_the_same_item_is_a_different_lesson(db, receipt):
    _add(db, receipt, "MLK WHL GAL", "Whole Milk", 1)
    _add(db, receipt, "4.29", "8.58", 2, field="price")

    assert len(_lines(get_correction_prompt(db))) == 2


def test_the_newest_copy_is_the_one_kept(db, receipt):
    """Ordering is unchanged: the block is still newest first."""
    _add(db, receipt, "OLD LESSON", "Old Lesson", 60)
    for minutes in range(3):
        _add(db, receipt, "NEW LESSON", "New Lesson", minutes)

    lines = _lines(get_correction_prompt(db))

    assert len(lines) == 2
    assert "New Lesson" in lines[0]
    assert "Old Lesson" in lines[1]
