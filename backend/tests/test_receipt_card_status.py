"""Audit finding 16: the receipts list never showed that an upload failed.

`_render_receipt_card_html` read neither `receipt.status` nor
`receipt.error_message`. A failed upload rendered as an ordinary card —
"Unknown Store, $0.00, 0 items" — indistinguishable from a receipt that parsed
to nothing. The live database has one such receipt, failed with
"All Gemini models failed. Last: 400 INVALID_ARGUMENT", sitting in the list
looking entirely normal.

The bulk import page already did this properly, so the vocabulary is borrowed
from there.
"""

from __future__ import annotations

import pytest

from app.models import Receipt, Store


@pytest.fixture
def store(db):
    s = Store(name="Corner Shop")
    db.add(s)
    db.commit()
    return s


def _receipt(db, store, status, error=None):
    r = Receipt(store_id=store.id, total_amount=0.0, status=status, error_message=error)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _list(client) -> str:
    resp = client.get("/api/receipts/list")
    assert resp.status_code == 200
    return str(resp.text)


class TestFailedUploadsAreVisible:
    def test_the_card_is_badged(self, client, db, store):
        _receipt(db, store, "failed", "All Gemini models failed. Last: 400")
        body = _list(client)
        assert "Failed" in body, "a failed upload still looks like an ordinary receipt"

    def test_the_reason_is_shown(self, client, db, store):
        _receipt(db, store, "failed", "All Gemini models failed. Last: 400")
        assert "All Gemini models failed" in _list(client)

    def test_the_card_is_marked_out(self, client, db, store):
        _receipt(db, store, "failed", "boom")
        assert "ring-red-500/30" in _list(client)

    def test_a_failure_with_no_message_still_badges(self, client, db, store):
        _receipt(db, store, "failed", None)
        assert "Failed" in _list(client)

    def test_the_message_is_escaped(self, client, db, store):
        """error_message carries whatever the backend or model API said."""
        _receipt(db, store, "failed", "<img src=x onerror=window.__pwned=1>")
        body = _list(client)
        assert "<img src=x onerror=" not in body
        assert "&lt;img src=x onerror=" in body


class TestTheOtherStatuses:
    @pytest.mark.parametrize(
        ("status", "label"),
        [("processing", "Reading"), ("pending", "Waiting")],
    )
    def test_in_flight_states_are_named(self, client, db, store, status, label):
        _receipt(db, store, status)
        assert label in _list(client)

    def test_completed_receipts_are_not_badged(self, client, db, store):
        """412 of 413 receipts are completed; a badge on each would be noise."""
        _receipt(db, store, "completed")
        body = _list(client)
        for label in ("Failed", "Waiting", "Reading"):
            assert label not in body
        assert "ring-red-500/30" not in body

    def test_a_missing_status_reads_as_waiting(self, client, db, store):
        _receipt(db, store, None)
        assert "Waiting" in _list(client)


class TestTheSingleCardRefreshAgrees:
    """The list and the per-card refresh render through the same helper."""

    def test_it_badges_a_failure_too(self, client, db, store):
        r = _receipt(db, store, "failed", "nothing answered at localhost")
        resp = client.get(f"/api/receipts/{r.id}/card")
        assert resp.status_code == 200
        assert "Failed" in resp.text
        assert "nothing answered at localhost" in resp.text
