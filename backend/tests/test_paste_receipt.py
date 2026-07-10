"""Test the paste-receipt-text endpoint and text parsing flow.

Uses the conftest `client`/`db` fixtures (in-memory database) and stubs the
background AI task so no live model call is ever made from the test suite.
"""

import json

import pytest

from app.models import Receipt

SAMPLE_TEXT = (
    "Thanks for shopping with Safeway!\n"
    "Here is your receipt from 01/18/2026.\n"
    "Campbells Soup Chicken & Rice $0.99\n"
    "Quantity: 1\n"
    "Regular Price $2.49\n"
    "Total $0.99\n"
)


@pytest.fixture
def stub_text_task(monkeypatch):
    """Replace the background text-parse task with a recording no-op."""
    calls: list[tuple[int, str]] = []

    def _stub(receipt_id: int, raw_text: str) -> None:
        calls.append((receipt_id, raw_text))

    # Patch the name the endpoint actually schedules (imported into receipts.py)
    monkeypatch.setattr("app.api.receipts.process_text_receipt_task", _stub)
    return calls


# ---------------------------------------------------------------------------
# Endpoint validation tests (no AI call needed)
# ---------------------------------------------------------------------------


def test_paste_rejects_empty_text(client):
    """POST /api/receipts/paste should reject empty or very short text."""
    resp = client.post("/api/receipts/paste", json={"text": ""})
    assert resp.status_code == 400
    assert "too short" in resp.json()["detail"].lower()


def test_paste_rejects_short_text(client):
    """POST /api/receipts/paste should reject text under 20 chars."""
    resp = client.post("/api/receipts/paste", json={"text": "short"})
    assert resp.status_code == 400
    assert "too short" in resp.json()["detail"].lower()


def test_paste_rejects_oversized_text(client):
    """POST /api/receipts/paste should reject text over 50,000 chars."""
    resp = client.post("/api/receipts/paste", json={"text": "x" * 50_001})
    assert resp.status_code == 400
    assert "too long" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Receipt creation tests (AI task stubbed)
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("stub_text_task")
def test_paste_creates_pending_receipt(client, db):
    """POST /api/receipts/paste with valid text should create a pending receipt."""
    resp = client.post("/api/receipts/paste", json={"text": SAMPLE_TEXT})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["receipt_id"] > 0

    receipt = db.query(Receipt).filter(Receipt.id == data["receipt_id"]).first()
    assert receipt is not None
    assert receipt.status == "pending"
    assert receipt.image_path is None


def test_paste_schedules_background_task_with_text(client, stub_text_task):
    """The endpoint should schedule the text-parse task with the pasted text."""
    resp = client.post("/api/receipts/paste", json={"text": SAMPLE_TEXT})
    assert resp.status_code == 200
    receipt_id = resp.json()["receipt_id"]

    assert stub_text_task == [(receipt_id, SAMPLE_TEXT.strip())]


@pytest.mark.usefixtures("stub_text_task")
def test_paste_receipt_stores_text_paste_flag(client, db):
    """The created receipt's ocr_data should contain the text_paste flag."""
    resp = client.post("/api/receipts/paste", json={"text": SAMPLE_TEXT})
    assert resp.status_code == 200
    receipt_id = resp.json()["receipt_id"]

    receipt = db.query(Receipt).filter(Receipt.id == receipt_id).first()
    assert receipt is not None
    ocr_data = json.loads(receipt.ocr_data)
    assert ocr_data.get("text_paste") is True
