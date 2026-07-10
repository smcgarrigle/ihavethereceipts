from datetime import datetime

import pytest

from app.models import Receipt, Store


def test_review_receipt_valid(client, db):
    # Setup
    store = Store(name="Test Store")
    db.add(store)
    db.commit()

    receipt = Receipt(
        store_id=store.id, purchase_date=datetime.now(), total_amount=10.0, ocr_data='{"items": []}'
    )
    db.add(receipt)
    db.commit()

    response = client.get(f"/api/receipts/{receipt.id}/review")
    # Note: The route is actually defined in main.py under /receipts/{id}/review
    # But wait, app.include_router is used for api...
    # The route in main.py is @app.get("/receipts/{receipt_id}/review")
    # So it's not under /api prefix.

    response = client.get(f"/receipts/{receipt.id}/review")
    assert response.status_code == 200
    assert "Review Receipt" in response.text


def test_review_receipt_missing_date(client, db):
    """Test when purchase_date is None, which might cause 500"""
    store = Store(name="Test Store")
    db.add(store)
    db.commit()

    receipt = Receipt(
        store_id=store.id,
        purchase_date=None,  # Missing date
        total_amount=10.0,
        ocr_data=None,
    )
    db.add(receipt)
    db.commit()

    response = client.get(f"/receipts/{receipt.id}/review")
    # Check if this fails with 500
    if response.status_code == 500:
        pytest.fail("Endpoint returned 500 Internal Server Error")

    assert response.status_code == 200


def test_review_receipt_bad_json(client, db):
    """Test when ocr_data is invalid JSON"""
    store = Store(name="Test Store")
    db.add(store)
    db.commit()

    receipt = Receipt(
        store_id=store.id, purchase_date=datetime.now(), total_amount=10.0, ocr_data="INVALID JSON"
    )
    db.add(receipt)
    db.commit()

    response = client.get(f"/receipts/{receipt.id}/review")
    if response.status_code == 500:
        pytest.fail("Endpoint returned 500 Internal Server Error for bad JSON")

    assert response.status_code == 200
