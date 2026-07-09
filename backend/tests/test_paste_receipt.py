"""Test the paste-receipt-text endpoint and text parsing flow."""

import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Endpoint validation tests (no AI call needed)
# ---------------------------------------------------------------------------


def test_paste_rejects_empty_text():
    """POST /api/receipts/paste should reject empty or very short text."""
    resp = client.post(
        "/api/receipts/paste",
        json={"text": ""},
    )
    assert resp.status_code == 400
    assert "too short" in resp.json()["detail"].lower()


def test_paste_rejects_short_text():
    """POST /api/receipts/paste should reject text under 20 chars."""
    resp = client.post(
        "/api/receipts/paste",
        json={"text": "short"},
    )
    assert resp.status_code == 400
    assert "too short" in resp.json()["detail"].lower()


def test_paste_creates_pending_receipt():
    """POST /api/receipts/paste with valid text should create a pending receipt."""
    sample_text = (
        "Thanks for shopping with Safeway!\n"
        "Here is your receipt from 01/18/2026.\n"
        "Campbells Soup Chicken & Rice $0.99\n"
        "Quantity: 1\n"
        "Regular Price $2.49\n"
        "Total $0.99\n"
    )
    resp = client.post(
        "/api/receipts/paste",
        json={"text": sample_text},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "receipt_id" in data
    assert data["receipt_id"] > 0

    # Verify the receipt was created in the database
    status_resp = client.get(f"/api/receipts/{data['receipt_id']}/status")
    assert status_resp.status_code == 200
    # Status could be pending or completed depending on background task timing
    assert status_resp.json()["status"] in ("pending", "completed", "failed")


def test_paste_receipt_stores_text_paste_flag():
    """The created receipt's ocr_data should contain the text_paste flag."""
    from app.database import SessionLocal
    from app.models import Receipt

    sample_text = (
        "Rainbow Grocery receipt\n"
        "Date: July 08, 2026\n"
        "Organic Bananas $1.29\n"
        "Quantity: 1\n"
        "Total $1.29\n"
    )
    resp = client.post(
        "/api/receipts/paste",
        json={"text": sample_text},
    )
    assert resp.status_code == 200
    receipt_id = resp.json()["receipt_id"]

    db = SessionLocal()
    try:
        receipt = db.query(Receipt).filter(Receipt.id == receipt_id).first()
        assert receipt is not None
        ocr_data = json.loads(receipt.ocr_data)
        assert ocr_data.get("text_paste") is True
    finally:
        db.close()
