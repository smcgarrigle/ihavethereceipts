"""CM-05: the size of the corrections block is a setting, not a constant.

The block held ten lessons because ten was written into the signature. It is
now CORRECTION_PROMPT_LIMIT, read per call so a change applies without a
restart. A limit counts distinct lessons, so these fixtures give every row its
own content key and the dedupe pass leaves them alone.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.models import OcrCorrection, Receipt, Store
from app.services.correction_keys import content_key
from app.services.correction_service import (
    _DEFAULT_CORRECTION_PROMPT_LIMIT,
    get_correction_prompt,
)


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


def _add_lessons(db, receipt, count):
    """``count`` distinct lessons, aged so ordering is deterministic."""
    for i in range(count):
        row = OcrCorrection(
            receipt_id=receipt.id,
            store_id=receipt.store_id,
            field="name",
            input_type="image",
            ai_value=f"AI NAME {i}",
            approved_value=f"Real Name {i}",
            created_at=datetime.now(UTC) - timedelta(minutes=i),
        )
        row.content_key = content_key(
            receipt.store_id, "image", "name", row.ai_value, row.approved_value
        )
        db.add(row)
    db.commit()


def _lines(block):
    return [line for line in block.splitlines() if line.startswith("- ")]


def test_the_default_is_ten_when_the_setting_is_unset(db, receipt, monkeypatch):
    monkeypatch.delenv("CORRECTION_PROMPT_LIMIT", raising=False)
    _add_lessons(db, receipt, 25)

    assert len(_lines(get_correction_prompt(db))) == 10
    assert _DEFAULT_CORRECTION_PROMPT_LIMIT == 10


def test_the_setting_raises_the_number_of_lessons(db, receipt, monkeypatch):
    monkeypatch.setenv("CORRECTION_PROMPT_LIMIT", "25")
    _add_lessons(db, receipt, 40)

    lines = _lines(get_correction_prompt(db))

    assert len(lines) == 25
    assert len(set(lines)) == 25


def test_the_setting_lowers_the_number_of_lessons(db, receipt, monkeypatch):
    monkeypatch.setenv("CORRECTION_PROMPT_LIMIT", "3")
    _add_lessons(db, receipt, 20)

    assert len(_lines(get_correction_prompt(db))) == 3


def test_a_larger_limit_still_reads_past_the_dedupe_floor(db, receipt, monkeypatch):
    """The pre-read is a multiple of the limit, so a raised limit still fills.

    The floor of 50 rows is enough for the default but not for a limit of 25,
    which is what the multiplier is for.
    """
    monkeypatch.setenv("CORRECTION_PROMPT_LIMIT", "25")
    _add_lessons(db, receipt, 60)

    assert len(_lines(get_correction_prompt(db))) == 25


def test_an_explicit_limit_wins_over_the_setting(db, receipt, monkeypatch):
    """The eval harness compares block sizes and must not be overridden."""
    monkeypatch.setenv("CORRECTION_PROMPT_LIMIT", "25")
    _add_lessons(db, receipt, 30)

    assert len(_lines(get_correction_prompt(db, limit=5))) == 5


@pytest.mark.parametrize("bad", ["0", "-3", "ten", "", "   ", "7.5"])
def test_an_unusable_setting_falls_back_to_the_default(db, receipt, monkeypatch, bad):
    """A limit under 1 would send an empty block and quietly disable the feature."""
    monkeypatch.setenv("CORRECTION_PROMPT_LIMIT", bad)
    _add_lessons(db, receipt, 25)

    assert len(_lines(get_correction_prompt(db))) == 10


def test_the_setting_is_read_per_call_not_at_import(db, receipt, monkeypatch):
    """A change applies to the next receipt, without restarting the app."""
    _add_lessons(db, receipt, 20)

    monkeypatch.setenv("CORRECTION_PROMPT_LIMIT", "4")
    assert len(_lines(get_correction_prompt(db))) == 4

    monkeypatch.setenv("CORRECTION_PROMPT_LIMIT", "9")
    assert len(_lines(get_correction_prompt(db))) == 9
