"""Audit finding 02: an uploaded receipt must be processed exactly once.

The upload endpoint's BackgroundTasks, the bulk worker's poll loop and the
folder watcher all reach process_receipt_task for the same row. The claim is
what arbitrates: one conditional UPDATE from pending to processing.
"""

import datetime
from unittest.mock import patch

import pytest
from conftest import TestingSessionLocal

from app.models import Receipt, Store
from app.services.bulk_processor import BulkProcessor
from app.services.receipt_claim import claim_receipt


def release(session):
    """Commit and detach, so a second Session can BEGIN on the shared connection.

    conftest pins every session to one in-memory SQLite connection via
    StaticPool; a lingering transaction here makes the task's own session fail
    with "cannot start a transaction within a transaction".
    """
    session.commit()
    session.close()


@pytest.fixture
def pending_receipt(db):
    store = Store(name="Claim Test Store")
    db.add(store)
    db.commit()
    db.refresh(store)

    receipt = Receipt(
        store_id=store.id,
        image_path="/tmp/claim-test.jpg",
        total_amount=0.0,
        purchase_date=datetime.datetime.now(),
        status="pending",
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt


def test_only_the_first_claim_wins(db, pending_receipt):
    """Two callers racing for one receipt: exactly one may process it."""
    assert claim_receipt(db, pending_receipt.id) is True
    assert claim_receipt(db, pending_receipt.id) is False

    db.refresh(pending_receipt)
    assert pending_receipt.status == "processing"


def test_claim_refuses_a_receipt_that_is_not_pending(db, pending_receipt):
    pending_receipt.status = "completed"
    db.commit()

    assert claim_receipt(db, pending_receipt.id) is False

    db.refresh(pending_receipt)
    assert pending_receipt.status == "completed"


def test_force_claims_any_status(db, pending_receipt):
    """The manual reprocess script deliberately re-runs a finished receipt."""
    pending_receipt.status = "completed"
    db.commit()

    assert claim_receipt(db, pending_receipt.id, force=True) is True

    db.refresh(pending_receipt)
    assert pending_receipt.status == "processing"


def test_claim_on_a_missing_receipt_is_false(db):
    assert claim_receipt(db, 999999) is False


def test_worker_claims_the_row_it_returns(db, pending_receipt):
    worker = BulkProcessor()

    claimed = worker._claim_next_pending(db)

    assert claimed is not None
    assert claimed.id == pending_receipt.id
    db.refresh(pending_receipt)
    assert pending_receipt.status == "processing"


def test_worker_will_not_hand_out_the_same_receipt_twice(db, pending_receipt):
    worker = BulkProcessor()

    first = worker._claim_next_pending(db)
    assert first is not None and first.id == pending_receipt.id
    assert worker._claim_next_pending(db) is None


def test_worker_backs_off_when_it_loses_the_claim(db, pending_receipt):
    """Upload got there first between the poll and the claim."""
    worker = BulkProcessor()

    with patch("app.services.bulk_processor.claim_receipt", return_value=False):
        assert worker._claim_next_pending(db) is None

    db.refresh(pending_receipt)
    assert pending_receipt.status == "pending"


def test_task_skips_a_receipt_already_being_processed(db, pending_receipt):
    """The loser of the race must not run OCR a second time."""
    pending_receipt.status = "processing"
    receipt_id = pending_receipt.id
    release(db)

    from app.services.ocr import process_receipt_task

    with (
        patch("app.database.SessionLocal", TestingSessionLocal),
        patch("app.services.ocr.process_receipt_image") as mock_ocr,
    ):
        process_receipt_task(receipt_id, "/tmp/claim-test.jpg")

    assert not mock_ocr.called, "OCR ran on a receipt owned by another worker"


def test_task_claims_a_pending_receipt_and_proceeds(db, pending_receipt):
    receipt_id = pending_receipt.id
    release(db)

    from app.services.ocr import process_receipt_task

    with (
        patch("app.database.SessionLocal", TestingSessionLocal),
        patch(
            "app.services.ocr.process_receipt_image",
            return_value={"error": "stopped in test"},
        ) as mock_ocr,
    ):
        process_receipt_task(receipt_id, "/tmp/claim-test.jpg")

    assert mock_ocr.called, "The task refused a receipt that was pending"
    assert db.query(Receipt).filter(Receipt.id == receipt_id).one().status == "failed"


def test_worker_ignores_a_receipt_the_upload_path_already_took(db, pending_receipt):
    """End to end: upload's background task runs, the poller finds nothing to do."""
    receipt_id = pending_receipt.id
    release(db)

    from app.services.ocr import process_receipt_task

    with (
        patch("app.database.SessionLocal", TestingSessionLocal),
        patch(
            "app.services.ocr.process_receipt_image",
            return_value={"error": "stopped in test"},
        ),
    ):
        process_receipt_task(receipt_id, "/tmp/claim-test.jpg")

    assert BulkProcessor()._claim_next_pending(db) is None
