"""CM-09: a pinned lesson stays in its block regardless of age.

The block is the newest N lessons, so a lesson that matters but stops being
recorded falls out of it. A pin holds it in. Pins fill first and the newest
corrections take what is left, so a pin costs a slot rather than adding one.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from app.models import OcrCorrection, Receipt, Store
from app.services.correction_keys import content_key
from app.services.correction_service import (
    get_correction_prompt,
    pinned_keys,
    select_corrections,
    set_pinned,
    set_suppressed,
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


def _lesson(db, receipt, ai_value, approved_value, minutes_ago=0, input_type="image"):
    row = OcrCorrection(
        receipt_id=receipt.id,
        store_id=receipt.store_id,
        field="name",
        input_type=input_type,
        ai_value=ai_value,
        approved_value=approved_value,
        content_key=content_key(receipt.store_id, input_type, "name", ai_value, approved_value),
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


def test_pinning_creates_an_override_carrying_the_lesson(db):
    row = _lesson(db, _receipt(db, _store(db)), "MLK WHL GAL", "Whole Milk")

    override = set_pinned(db, row)

    assert override.pinned is True
    assert override.suppressed is False
    assert override.content_key == row.content_key
    assert override.ai_value == "MLK WHL GAL"


def test_a_lesson_can_be_released(db):
    row = _lesson(db, _receipt(db, _store(db)), "MLK WHL GAL", "Whole Milk")

    set_pinned(db, row)
    assert row.content_key in pinned_keys(db)

    set_pinned(db, row, pinned=False)
    assert row.content_key not in pinned_keys(db)


def test_one_override_carries_both_decisions(db):
    """Pinning and suppressing the same lesson writes one row, not two."""
    from app.models import CorrectionOverride

    row = _lesson(db, _receipt(db, _store(db)), "MLK WHL GAL", "Whole Milk")

    set_pinned(db, row)
    set_suppressed(db, row)

    override = db.query(CorrectionOverride).filter_by(content_key=row.content_key).one()
    assert override.pinned is True
    assert override.suppressed is True


def test_a_correction_without_a_key_cannot_be_pinned(db):
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
        set_pinned(db, row)


# ---------------------------------------------------------------------------
# Pins fill first
# ---------------------------------------------------------------------------


def test_a_pinned_lesson_survives_past_the_limit(db):
    """The whole point: too old for the newest ten, kept anyway."""
    receipt = _receipt(db, _store(db))
    old = _lesson(db, receipt, "OLD LESSON", "Old Lesson", 500)
    for i in range(12):
        _lesson(db, receipt, f"AI {i}", f"Real {i}", i)

    assert "Old Lesson" not in get_correction_prompt(db)

    set_pinned(db, old)
    lines = _lines(get_correction_prompt(db))

    assert len(lines) == 10
    assert "Old Lesson" in lines[0]


def test_pins_come_before_the_newest(db):
    receipt = _receipt(db, _store(db))
    old = _lesson(db, receipt, "OLD LESSON", "Old Lesson", 500)
    _lesson(db, receipt, "NEW LESSON", "New Lesson", 1)

    set_pinned(db, old)
    lines = _lines(get_correction_prompt(db))

    assert "Old Lesson" in lines[0]
    assert "New Lesson" in lines[1]


def test_a_pin_costs_a_slot_rather_than_adding_one(db):
    receipt = _receipt(db, _store(db))
    old = _lesson(db, receipt, "OLD LESSON", "Old Lesson", 500)
    for i in range(12):
        _lesson(db, receipt, f"AI {i}", f"Real {i}", i)

    set_pinned(db, old)

    assert len(_lines(get_correction_prompt(db))) == 10


def test_a_pinned_lesson_is_not_repeated_in_the_fill(db):
    receipt = _receipt(db, _store(db))
    row = _lesson(db, receipt, "MLK WHL GAL", "Whole Milk", 1)
    _lesson(db, receipt, "ORG SPNCH", "Organic Spinach", 2)

    set_pinned(db, row)
    lines = _lines(get_correction_prompt(db))

    assert len(lines) == 2
    assert sum("Whole Milk" in line for line in lines) == 1


def test_more_pins_than_the_limit_keeps_the_newest_pins(db):
    """A pin asks to be included, not to make the prompt bigger."""
    receipt = _receipt(db, _store(db))
    rows = [_lesson(db, receipt, f"AI {i}", f"Real {i}", i) for i in range(12)]
    for row in rows:
        set_pinned(db, row)

    lines = _lines(get_correction_prompt(db))

    assert len(lines) == 10
    assert "Real 0" in lines[0]
    assert all("Real 11" not in line for line in lines)


def test_no_pins_leaves_the_block_unchanged(db):
    receipt = _receipt(db, _store(db))
    for i in range(3):
        _lesson(db, receipt, f"AI {i}", f"Real {i}", i)

    assert len(_lines(get_correction_prompt(db))) == 3


# ---------------------------------------------------------------------------
# A pin applies only to its own store and input type
# ---------------------------------------------------------------------------


def test_a_pin_does_not_reach_another_store(db):
    costco = _store(db)
    safeway = _store(db, "Safeway")
    pinned = _lesson(db, _receipt(db, costco), "MLK WHL GAL", "Whole Milk", 500)
    _lesson(db, _receipt(db, safeway, "/data/uploads/s.jpg"), "SFWY LINE", "Safeway Line", 1)

    set_pinned(db, pinned)
    block = get_correction_prompt(db, store_name="Safeway", input_type="image")

    assert "Safeway Line" in block
    assert "Whole Milk" not in block


def test_a_pin_does_not_reach_another_input_type(db):
    store = _store(db)
    image_receipt = _receipt(db, store)
    paste_receipt = _receipt(db, store, None)
    pinned = _lesson(db, image_receipt, "IMAGE LINE", "Image Line", 500)
    _lesson(db, paste_receipt, "PASTE LINE", "Paste Line", 1, input_type="paste")

    set_pinned(db, pinned)
    block = get_correction_prompt(db, input_type="paste")

    assert "Paste Line" in block
    assert "Image Line" not in block


def test_a_pin_reaches_its_own_store_block(db):
    store = _store(db)
    receipt = _receipt(db, store)
    pinned = _lesson(db, receipt, "MLK WHL GAL", "Whole Milk", 500)
    for i in range(12):
        _lesson(db, receipt, f"AI {i}", f"Real {i}", i)

    set_pinned(db, pinned)
    block = get_correction_prompt(db, store_name="Costco", input_type="image")

    assert "Costco" in block
    assert "Whole Milk" in block


# ---------------------------------------------------------------------------
# Pins against the other rules
# ---------------------------------------------------------------------------


def test_suppression_beats_a_pin(db):
    """Both decisions on one lesson: removed wins, so a pin cannot resurrect it."""
    row = _lesson(db, _receipt(db, _store(db)), "MLK WHL GAL", "Whole Milk")

    set_pinned(db, row)
    set_suppressed(db, row)

    assert get_correction_prompt(db) == ""


def test_a_pin_does_not_hand_a_receipt_its_own_answers(db):
    """Exclusion still applies, or a pinned lesson would leak into an eval."""
    receipt = _receipt(db, _store(db))
    row = _lesson(db, receipt, "MLK WHL GAL", "Whole Milk", 500)
    set_pinned(db, row)

    rows, _ = select_corrections(db, exclude_receipt_ids=[receipt.id])

    assert rows == []


def test_a_pin_on_a_lesson_no_longer_recorded_does_nothing(db):
    """Pins select from stored corrections; they do not re-create a deleted row."""
    receipt = _receipt(db, _store(db))
    row = _lesson(db, receipt, "MLK WHL GAL", "Whole Milk")
    key = row.content_key
    set_pinned(db, row)

    db.delete(row)
    db.commit()

    assert key in pinned_keys(db)
    assert get_correction_prompt(db) == ""


def test_a_lookup_failure_returns_no_pins(db):
    with patch.object(db, "query", side_effect=RuntimeError("table is gone")):
        assert pinned_keys(db) == set()


def test_a_lookup_failure_leaves_the_newest_block(db):
    """Losing the pins costs the pin, not the prompt."""
    receipt = _receipt(db, _store(db))
    old = _lesson(db, receipt, "OLD LESSON", "Old Lesson", 500)
    _lesson(db, receipt, "NEW LESSON", "New Lesson", 1)
    set_pinned(db, old)

    with patch("app.services.correction_service.pinned_keys", return_value=set()):
        lines = _lines(get_correction_prompt(db))

    assert "New Lesson" in lines[0]
