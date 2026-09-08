"""Audit finding 19: the stuck-receipt sweeper compared clocks.

`datetime.now() - timedelta(hours=1)` is local, while `created_at` defaults to
`server_default=func.now()`, which SQLite renders as UTC. East of Greenwich the
cutoff sits in the future relative to stored values, so a receipt becomes
eligible for "Processing timeout" the moment it is created; west of it, a
genuinely stuck receipt waits that many hours longer. On this machine (PDT,
UTC-7) the one-hour timeout was effectively eight.

The two datetime columns on `receipts` really are on different clocks:
`created_at` is UTC via the server default, `purchase_date` is written with a
naive local `datetime.now()`. So the rule is not "use UTC everywhere" — it is
"use the clock the column is on", which is why analytics.py's 30-day window
moves the other way.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest

from app.models import Receipt, Store
from app.services.bulk_processor import STUCK_AFTER, BulkProcessor


@pytest.fixture
def store(db):
    s = Store(name="Sweeper Shop")
    db.add(s)
    db.commit()
    return s


def _processing(db, store, age: timedelta):
    """A receipt stuck in processing, created `age` ago on the UTC clock."""
    r = Receipt(
        store_id=store.id,
        status="processing",
        created_at=(datetime.now(UTC) - age).replace(tzinfo=None),
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _status(db, receipt_id: str | int) -> str | None:
    db.expire_all()
    status = db.query(Receipt).filter(Receipt.id == receipt_id).one().status
    return str(status) if status is not None else None


class TestTheCutoffUsesTheColumnsClock:
    def test_a_genuinely_stuck_receipt_is_swept(self, db, store):
        stuck = _processing(db, store, timedelta(hours=2))
        assert BulkProcessor._reset_stuck_processing(db) == 1
        assert _status(db, stuck.id) == "failed"

    def test_a_fresh_receipt_is_left_alone(self, db, store):
        fresh = _processing(db, store, timedelta(minutes=1))
        assert BulkProcessor._reset_stuck_processing(db) == 0
        assert _status(db, fresh.id) == "processing"

    def test_just_inside_the_window_survives(self, db, store):
        """The pre-fix code swept this immediately anywhere east of Greenwich."""
        recent = _processing(db, store, STUCK_AFTER - timedelta(minutes=5))
        assert BulkProcessor._reset_stuck_processing(db) == 0
        assert _status(db, recent.id) == "processing"

    def test_just_outside_the_window_is_swept(self, db, store):
        """And the pre-fix code left this for another seven hours in PDT."""
        old = _processing(db, store, STUCK_AFTER + timedelta(minutes=5))
        assert BulkProcessor._reset_stuck_processing(db) == 1
        assert _status(db, old.id) == "failed"

    def test_the_reason_is_recorded(self, db, store):
        stuck = _processing(db, store, timedelta(hours=3))
        BulkProcessor._reset_stuck_processing(db)
        db.expire_all()
        row = db.query(Receipt).filter(Receipt.id == stuck.id).one()
        assert "timeout" in (row.error_message or "").lower()

    @pytest.mark.parametrize(
        "tz", ["UTC", "Australia/Sydney", "America/Los_Angeles", "Asia/Kolkata"]
    )
    def test_it_holds_in_any_timezone(self, db, store, tz, monkeypatch):
        """The point of the finding: the verdict must not depend on the offset.

        Sydney is UTC+10, which is where the pre-fix code swept everything
        instantly; Los Angeles is UTC-7, where nothing was swept for hours.
        """
        monkeypatch.setenv("TZ", tz)
        time.tzset()
        try:
            fresh = _processing(db, store, timedelta(minutes=1))
            old = _processing(db, store, timedelta(hours=5))
            assert BulkProcessor._reset_stuck_processing(db) == 1
            assert _status(db, fresh.id) == "processing", f"swept a fresh receipt in {tz}"
            assert _status(db, old.id) == "failed", f"missed a stuck receipt in {tz}"
        finally:
            monkeypatch.delenv("TZ", raising=False)
            time.tzset()


class TestOtherStatusesAreUntouched:
    @pytest.mark.parametrize("status", ["pending", "completed", "failed"])
    def test_only_processing_is_swept(self, db, store, status):
        r = Receipt(
            store_id=store.id,
            status=status,
            created_at=(datetime.now(UTC) - timedelta(days=2)).replace(tzinfo=None),
        )
        db.add(r)
        db.commit()
        db.refresh(r)

        assert BulkProcessor._reset_stuck_processing(db) == 0
        assert _status(db, r.id) == status


class TestTheAnalyticsWindowUsesTheOtherClock:
    def test_a_receipt_bought_moments_ago_is_in_the_last_30_days(self, client, db, store):
        """purchase_date is local, so the cutoff must be local too.

        With a UTC cutoff this window is short by the machine's offset — seven
        hours here — which silently clips the newest purchases.
        """
        r = Receipt(
            store_id=store.id,
            status="completed",
            total_amount=10.0,
            purchase_date=datetime.now() - timedelta(minutes=2),
        )
        db.add(r)
        db.commit()

        resp = client.get("/api/analytics/bi-dashboard")
        assert resp.status_code == 200
