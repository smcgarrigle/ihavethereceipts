"""CM-14: the estimated usage report has to stay honest.

The report reconstructs what the prompt *would* have carried before CM-07
started logging. That makes it useful and makes it dangerous: a reconstruction
that quietly drops its caveats reads exactly like a record.

So these tests pin the two things that matter — the replay only ever sees
corrections that existed at the moment being replayed, and the caveats are
present in the output — alongside the selection rules it mirrors.

The script lives in scripts/ rather than the app package, so it is loaded by
path, as in test_correction_backfill_check.py.
"""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.models import CorrectionUsage, OcrCorrection, Receipt, Store
from app.services.correction_keys import content_key

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "estimated_usage_report.py"


@pytest.fixture(scope="module")
def report_script():
    spec = importlib.util.spec_from_file_location("cm14_report", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _store(db, name="Costco"):
    store = db.query(Store).filter_by(name=name).first()
    if not store:
        store = Store(name=name)
        db.add(store)
        db.commit()
    return store


def _receipt(db, store, image_path="/data/uploads/a.jpg", days_ago=0):
    receipt = Receipt(
        status="completed",
        store_id=store.id,
        image_path=image_path,
        created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days_ago),
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt


def _lesson(
    db,
    receipt,
    ai_value="MLK WHL GAL",
    approved_value="Whole Milk",
    field="name",
    input_type="image",
    days_ago=0,
):
    row = OcrCorrection(
        receipt_id=receipt.id,
        store_id=receipt.store_id,
        field=field,
        input_type=input_type,
        ai_value=ai_value,
        approved_value=approved_value,
        content_key=content_key(receipt.store_id, input_type, field, ai_value, approved_value),
        created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days_ago),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# The replay only sees the past
# ---------------------------------------------------------------------------


def test_the_pool_excludes_corrections_recorded_later(report_script, db):
    """The whole point: a receipt cannot have been prompted with the future."""
    store = _store(db)
    source = _receipt(db, store, days_ago=30)
    old = _lesson(db, source, "OLD", "Old Lesson", days_ago=20)
    _lesson(db, source, "NEW", "New Lesson", days_ago=1)

    corrections = sorted(db.query(OcrCorrection).all(), key=lambda c: c.created_at)
    moment = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=10)

    pool = report_script._pool_at(corrections, moment)

    assert [c.ai_value for c in pool] == ["OLD"]
    assert old.ai_value == "OLD"


def test_the_pool_is_newest_first(report_script, db):
    store = _store(db)
    source = _receipt(db, store, days_ago=30)
    for day, value in ((20, "OLDEST"), (10, "MIDDLE"), (5, "NEWEST")):
        _lesson(db, source, value, f"{value} Lesson", days_ago=day)

    corrections = sorted(db.query(OcrCorrection).all(), key=lambda c: c.created_at)
    pool = report_script._pool_at(corrections, datetime.now(UTC).replace(tzinfo=None))

    assert [c.ai_value for c in pool] == ["NEWEST", "MIDDLE", "OLDEST"]


def test_an_empty_pool_before_any_correction(report_script, db):
    store = _store(db)
    source = _receipt(db, store, days_ago=30)
    _lesson(db, source, days_ago=5)

    corrections = sorted(db.query(OcrCorrection).all(), key=lambda c: c.created_at)
    moment = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=20)

    assert report_script._pool_at(corrections, moment) == []


# ---------------------------------------------------------------------------
# The selection mirrors the prompt block
# ---------------------------------------------------------------------------


def test_selection_prefers_the_receipt_s_own_store(report_script, db):
    costco = _store(db)
    safeway = _store(db, "Safeway")
    mine = _lesson(db, _receipt(db, costco, days_ago=10), "COSTCO", "Costco Line", days_ago=5)
    _lesson(
        db,
        _receipt(db, safeway, "/data/uploads/s.jpg", days_ago=10),
        "SFWY",
        "Safeway Line",
        days_ago=5,
    )

    pool = sorted(db.query(OcrCorrection).all(), key=lambda c: c.created_at, reverse=True)
    chosen = report_script._select(pool, costco.id, "image", 10)

    assert [c.ai_value for c in chosen] == ["COSTCO"]
    assert mine.store_id == costco.id


def test_selection_falls_back_to_every_store(report_script, db):
    costco = _store(db)
    safeway = _store(db, "Safeway")
    _lesson(db, _receipt(db, costco, days_ago=10), "COSTCO", "Costco Line", days_ago=5)

    pool = sorted(db.query(OcrCorrection).all(), key=lambda c: c.created_at, reverse=True)
    chosen = report_script._select(pool, safeway.id, "image", 10)

    assert [c.ai_value for c in chosen] == ["COSTCO"]


def test_selection_keeps_to_one_input_type(report_script, db):
    store = _store(db)
    _lesson(db, _receipt(db, store, days_ago=10), "IMAGE", "Image Line", days_ago=5)
    _lesson(
        db,
        _receipt(db, store, None, days_ago=10),
        "PASTE",
        "Paste Line",
        input_type="paste",
        days_ago=5,
    )

    pool = sorted(db.query(OcrCorrection).all(), key=lambda c: c.created_at, reverse=True)

    assert [c.ai_value for c in report_script._select(pool, store.id, "paste", 10)] == ["PASTE"]
    assert [c.ai_value for c in report_script._select(pool, store.id, "image", 10)] == ["IMAGE"]


def test_selection_collapses_repeats(report_script, db):
    store = _store(db)
    for day in (9, 7, 5):
        _lesson(db, _receipt(db, store, f"/data/uploads/{day}.jpg", days_ago=10), days_ago=day)

    pool = sorted(db.query(OcrCorrection).all(), key=lambda c: c.created_at, reverse=True)

    assert len(report_script._select(pool, store.id, "image", 10)) == 1


def test_selection_honours_the_limit(report_script, db):
    store = _store(db)
    for i in range(12):
        _lesson(
            db,
            _receipt(db, store, f"/data/uploads/{i}.jpg", days_ago=20),
            f"AI {i}",
            f"Real {i}",
            days_ago=10 - (i * 0.5),
        )

    pool = sorted(db.query(OcrCorrection).all(), key=lambda c: c.created_at, reverse=True)

    assert len(report_script._select(pool, store.id, "image", 4)) == 4


# ---------------------------------------------------------------------------
# The report says what it is
# ---------------------------------------------------------------------------


def test_the_report_carries_its_caveats(report_script, db):
    store = _store(db)
    source = _receipt(db, store, days_ago=30)
    _lesson(db, source, days_ago=20)
    _receipt(db, store, "/data/uploads/later.jpg", days_ago=5)

    report = report_script.build_report(db, limit=10, top=10)

    assert "This is an estimate" in report
    assert "re-save times" in report
    assert "Suppression and pins are applied as they stand today" in report
    assert "Nothing here is written to `correction_usage`" in report


def test_the_report_counts_re_saves(report_script, db):
    """A correction recorded long after its receipt is a re-save."""
    store = _store(db)
    source = _receipt(db, store, days_ago=30)
    _lesson(db, source, "PROMPT", "Prompt Lesson", days_ago=30)
    _lesson(db, source, "LATER", "Later Lesson", days_ago=2)

    report = report_script.build_report(db, limit=10, top=10)

    assert "1 of 2 correction timestamps are re-save times" in report


def test_the_report_writes_no_usage_rows(report_script, db):
    store = _store(db)
    source = _receipt(db, store, days_ago=30)
    _lesson(db, source, days_ago=20)
    _receipt(db, store, "/data/uploads/later.jpg", days_ago=5)

    report_script.build_report(db, limit=10, top=10)

    assert db.query(CorrectionUsage).count() == 0


def test_the_report_handles_an_empty_log(report_script, db):
    report = report_script.build_report(db, limit=10, top=10)

    assert "No corrections recorded" in report


def test_a_lesson_appears_with_its_send_count(report_script, db):
    store = _store(db)
    source = _receipt(db, store, days_ago=30)
    _lesson(db, source, days_ago=25)
    for day in (10, 5, 1):
        _receipt(db, store, f"/data/uploads/{day}.jpg", days_ago=day)

    report = report_script.build_report(db, limit=10, top=10)

    assert "Whole Milk" in report
    assert "| 3 |" in report, "three later receipts would each have carried the lesson"


def test_an_unknown_store_is_named_rather_than_blank(report_script, db):
    receipt = Receipt(
        status="completed",
        store_id=None,
        image_path="/data/uploads/a.jpg",
        created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30),
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    _lesson(db, receipt, days_ago=25)
    db.add(
        Receipt(
            status="completed",
            store_id=None,
            image_path="/data/uploads/b.jpg",
            created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=5),
        )
    )
    db.commit()

    report = report_script.build_report(db, limit=10, top=10)

    assert "Unknown Store" in report
