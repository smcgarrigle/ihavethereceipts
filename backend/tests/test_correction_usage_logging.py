"""CM-07: record which corrections went into which OCR call.

Usage answers two questions the log could not: how often a lesson is actually
sent, and what a given receipt was prompted with. The row refers to the lesson
by content key, because re-saving a review deletes and re-creates correction
rows under new ids.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from conftest import TestingSessionLocal

from app.models import CorrectionUsage, OcrCorrection, Receipt, Store
from app.services.correction_keys import content_key
from app.services.correction_service import log_correction_usage, select_corrections


def _store(db, name="Costco"):
    store = db.query(Store).filter_by(name=name).first()
    if not store:
        store = Store(name=name)
        db.add(store)
        db.commit()
    return store


def _receipt(db, store, image_path, status="completed"):
    receipt = Receipt(store_id=store.id, status=status, image_path=image_path, total_amount=0.0)
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt


def _lesson(db, receipt, ai_value, approved_value, minutes_ago=0, with_key=True):
    row = OcrCorrection(
        receipt_id=receipt.id,
        store_id=receipt.store_id,
        field="name",
        input_type="image",
        ai_value=ai_value,
        approved_value=approved_value,
        created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )
    if with_key:
        row.content_key = content_key(receipt.store_id, "image", "name", ai_value, approved_value)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _release(session):
    """Commit and close so the task's own session can BEGIN on the shared connection."""
    session.commit()
    session.close()


# ---------------------------------------------------------------------------
# The logging function itself
# ---------------------------------------------------------------------------


def test_one_row_per_correction(db):
    store = _store(db)
    source = _receipt(db, store, "/data/uploads/a.jpg")
    target = _receipt(db, store, "/data/uploads/b.jpg")
    rows = [_lesson(db, source, f"AI {i}", f"Real {i}", i) for i in range(3)]

    assert log_correction_usage(db, target.id, rows) == 3

    logged = db.query(CorrectionUsage).filter_by(receipt_id=target.id).all()
    assert len(logged) == 3
    assert {u.content_key for u in logged} == {r.content_key for r in rows}
    assert {u.correction_id for u in logged} == {r.id for r in rows}


def test_reprocessing_adds_a_second_set(db):
    """Usage counts how often a lesson was sent, not how many receipts saw it."""
    store = _store(db)
    source = _receipt(db, store, "/data/uploads/a.jpg")
    target = _receipt(db, store, "/data/uploads/b.jpg")
    rows = [_lesson(db, source, "MLK WHL GAL", "Whole Milk")]

    log_correction_usage(db, target.id, rows)
    log_correction_usage(db, target.id, rows)

    assert db.query(CorrectionUsage).filter_by(receipt_id=target.id).count() == 2


def test_nothing_selected_logs_nothing(db):
    store = _store(db)
    target = _receipt(db, store, "/data/uploads/b.jpg")

    assert log_correction_usage(db, target.id, []) == 0
    assert db.query(CorrectionUsage).count() == 0


def test_a_row_without_a_key_is_skipped(db):
    """Rows predating the key column have nothing durable to count against."""
    store = _store(db)
    source = _receipt(db, store, "/data/uploads/a.jpg")
    target = _receipt(db, store, "/data/uploads/b.jpg")
    keyed = _lesson(db, source, "MLK WHL GAL", "Whole Milk")
    unkeyed = _lesson(db, source, "ORG SPNCH", "Organic Spinach", with_key=False)

    assert log_correction_usage(db, target.id, [keyed, unkeyed]) == 1

    logged = db.query(CorrectionUsage).filter_by(receipt_id=target.id).all()
    assert [u.content_key for u in logged] == [keyed.content_key]


def test_usage_survives_the_correction_row_disappearing(db):
    """A re-save deletes the row; the usage record still names the lesson."""
    store = _store(db)
    source = _receipt(db, store, "/data/uploads/a.jpg")
    target = _receipt(db, store, "/data/uploads/b.jpg")
    row = _lesson(db, source, "MLK WHL GAL", "Whole Milk")
    key = row.content_key

    log_correction_usage(db, target.id, [row])
    db.delete(row)
    db.commit()

    usage = db.query(CorrectionUsage).filter_by(receipt_id=target.id).one()
    assert usage.content_key == key


def test_a_logging_failure_does_not_raise(db):
    """Bookkeeping must never cost a receipt its extraction."""
    store = _store(db)
    source = _receipt(db, store, "/data/uploads/a.jpg")
    target = _receipt(db, store, "/data/uploads/b.jpg")
    rows = [_lesson(db, source, "MLK WHL GAL", "Whole Milk")]

    with patch.object(db, "commit", side_effect=RuntimeError("database is locked")):
        assert log_correction_usage(db, target.id, rows) == 0


def test_the_session_still_works_after_a_logging_failure(db):
    store = _store(db)
    source = _receipt(db, store, "/data/uploads/a.jpg")
    target = _receipt(db, store, "/data/uploads/b.jpg")
    rows = [_lesson(db, source, "MLK WHL GAL", "Whole Milk")]

    with patch.object(db, "commit", side_effect=RuntimeError("database is locked")):
        log_correction_usage(db, target.id, rows)

    assert db.query(Receipt).filter_by(id=target.id).one().id == target.id


# ---------------------------------------------------------------------------
# What select_corrections hands back is what gets logged
# ---------------------------------------------------------------------------


def test_selection_returns_the_rows_and_the_scope(db):
    store = _store(db)
    receipt = _receipt(db, store, "/data/uploads/a.jpg")
    _lesson(db, receipt, "MLK WHL GAL", "Whole Milk")

    rows, scope = select_corrections(db, "Costco", input_type="image")

    assert [r.ai_value for r in rows] == ["MLK WHL GAL"]
    assert scope == "Costco"


def test_selection_reports_the_fallback_scope(db):
    store = _store(db)
    receipt = _receipt(db, store, "/data/uploads/a.jpg")
    _lesson(db, receipt, "MLK WHL GAL", "Whole Milk")

    rows, scope = select_corrections(db, "Nonexistent Mart", input_type="image")

    assert len(rows) == 1
    assert scope == "all stores"


def test_selection_rejects_an_unknown_input_type(db):
    with pytest.raises(ValueError):
        select_corrections(db, input_type="fax")


# ---------------------------------------------------------------------------
# The OCR tasks log what they sent
# ---------------------------------------------------------------------------


def _pending(db, image_path):
    store = _store(db, "Wiring Store")
    receipt = Receipt(store_id=store.id, status="pending", image_path=image_path, total_amount=0.0)
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt.id


@pytest.mark.parametrize(
    ("image_path", "ocr_function"),
    [
        ("/tmp/cm07-image.jpg", "process_receipt_image"),
        ("/tmp/cm07-order.pdf", "process_pdf_receipt"),
    ],
)
def test_the_upload_task_logs_what_it_sent(db, image_path, ocr_function):
    store = _store(db, "Wiring Store")
    source = _receipt(db, store, "/data/uploads/prior" + image_path[-4:])
    lesson = _lesson(db, source, "MLK WHL GAL", "Whole Milk")
    key = lesson.content_key
    receipt_id = _pending(db, image_path)
    _release(db)

    from app.services.ocr import process_receipt_task

    with (
        patch("app.database.SessionLocal", TestingSessionLocal),
        patch(f"app.services.ocr.{ocr_function}", return_value={"error": "stopped in test"}),
    ):
        process_receipt_task(receipt_id, image_path)

    check = TestingSessionLocal()
    try:
        logged = check.query(CorrectionUsage).filter_by(receipt_id=receipt_id).all()
    finally:
        check.close()

    assert [u.content_key for u in logged] == [key]


def test_the_paste_task_logs_what_it_sent(db):
    store = _store(db, "Wiring Store")
    source = _receipt(db, store, None)
    row = OcrCorrection(
        receipt_id=source.id,
        store_id=store.id,
        field="name",
        input_type="paste",
        ai_value="MLK WHL GAL",
        approved_value="Whole Milk",
        content_key=content_key(store.id, "paste", "name", "MLK WHL GAL", "Whole Milk"),
    )
    db.add(row)
    db.commit()
    key = row.content_key
    receipt_id = _pending(db, None)
    _release(db)

    from app.services.ocr import process_text_receipt_task

    with (
        patch("app.database.SessionLocal", TestingSessionLocal),
        patch("app.services.ocr.process_text_receipt", return_value={"error": "stopped in test"}),
    ):
        process_text_receipt_task(receipt_id, "Milk 4.29")

    check = TestingSessionLocal()
    try:
        logged = check.query(CorrectionUsage).filter_by(receipt_id=receipt_id).all()
    finally:
        check.close()

    assert [u.content_key for u in logged] == [key]


def test_an_empty_block_logs_nothing(db):
    """No corrections to send means no usage rows, not a row with nothing in it."""
    receipt_id = _pending(db, "/tmp/cm07-empty.jpg")
    _release(db)

    from app.services.ocr import process_receipt_task

    with (
        patch("app.database.SessionLocal", TestingSessionLocal),
        patch("app.services.ocr.process_receipt_image", return_value={"error": "stopped in test"}),
    ):
        process_receipt_task(receipt_id, "/tmp/cm07-empty.jpg")

    check = TestingSessionLocal()
    try:
        assert check.query(CorrectionUsage).count() == 0
    finally:
        check.close()


def test_a_logging_failure_does_not_stop_the_ocr_call(db):
    """The extraction still runs when the log write fails."""
    store = _store(db, "Wiring Store")
    source = _receipt(db, store, "/data/uploads/prior.jpg")
    _lesson(db, source, "MLK WHL GAL", "Whole Milk")
    receipt_id = _pending(db, "/tmp/cm07-fail.jpg")
    _release(db)

    from app.services.ocr import process_receipt_task

    with (
        patch("app.database.SessionLocal", TestingSessionLocal),
        patch(
            "app.services.correction_service.log_correction_usage",
            side_effect=RuntimeError("log is down"),
        ),
        patch(
            "app.services.ocr.process_receipt_image",
            return_value={"error": "stopped in test"},
        ) as extract,
    ):
        process_receipt_task(receipt_id, "/tmp/cm07-fail.jpg")

    assert extract.called, "a failure to log must not cost the receipt its extraction"
