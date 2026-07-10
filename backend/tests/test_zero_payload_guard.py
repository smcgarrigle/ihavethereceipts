"""
Guard against all-$0 save payloads wiping real receipt totals.

Regression for the July 2026 incident: ~209 receipts had correct OCR totals
overwritten with $0 by save-reviewed-items payloads whose every line was zero.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Receipt, ReceiptItem, Store


def _make_receipt(db: Session, total: float) -> Receipt:
    store = Store(name="Guard Test Store")
    db.add(store)
    db.commit()
    db.refresh(store)

    receipt = Receipt(store_id=store.id, total_amount=total, status="pending")
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt


def _item(name: str, price: float) -> dict:
    return {
        "name": name,
        "base_price": price,
        "quantity": 1.0,
        "discounts": [],
        "fees": [],
        "final_price": price,
        "category": "Other",
    }


def test_all_zero_payload_is_rejected(db: Session, client: TestClient):
    """An all-$0 payload must be refused with no writes at all."""
    receipt = _make_receipt(db, total=307.37)

    response = client.post(
        f"/api/receipts/{receipt.id}/save-reviewed-items",
        json={"items": [_item("ADVIL", 0.0), _item("BEEF VEG SP", 0.0)]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert "$0.00" in body["message"]

    db.refresh(receipt)
    assert receipt.total_amount == 307.37, "total must not be clobbered"
    assert receipt.status == "pending", "status must be untouched"
    lines = db.query(ReceiptItem).filter(ReceiptItem.receipt_id == receipt.id).count()
    assert lines == 0, "no receipt items may be written"


def test_all_zero_payload_allowed_with_explicit_total(db: Session, client: TestClient):
    """If the client states a receipt total, zero lines are its own choice."""
    receipt = _make_receipt(db, total=0.0)

    response = client.post(
        f"/api/receipts/{receipt.id}/save-reviewed-items",
        json={"items": [_item("Bag Refund", 0.0)], "total_amount": 12.50},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True

    db.refresh(receipt)
    assert receipt.total_amount == 12.50, "explicit total must survive a $0 item sum"


def test_partial_zero_lines_still_save(db: Session, client: TestClient):
    """Individual $0 lines (bag refunds, CRV) stay legal in a priced receipt."""
    receipt = _make_receipt(db, total=0.0)

    response = client.post(
        f"/api/receipts/{receipt.id}/save-reviewed-items",
        json={"items": [_item("Milk", 4.29), _item("Bag Refund", 0.0)]},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True

    db.refresh(receipt)
    assert receipt.total_amount == 4.29
    lines = db.query(ReceiptItem).filter(ReceiptItem.receipt_id == receipt.id).count()
    assert lines == 2
