from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models import Receipt

client = TestClient(app)


def test_zero_quantity_save_fix(db: Session, client: TestClient):
    """
    Test that saving a receipt item with quantity 0.0 defaults to 1.0
    and results in a correct (non-zero) receipt total.
    """
    # 1. Setup a dummy receipt
    # Note: store_id=1 requires a store to exist in the DB
    from app.models import Store

    store = Store(name="Test Store")
    db.add(store)
    db.commit()
    db.refresh(store)

    receipt = Receipt(store_id=store.id, total_amount=0.0, status="pending")
    db.add(receipt)
    db.commit()
    db.refresh(receipt)

    # 2. Mock a save request with quantity 0.0
    payload = {
        "items": [
            {
                "name": "Test Item Zero Qty",
                "base_price": 10.0,
                "quantity": 0.0,  # THE BUG TRIGGER
                "discounts": [],
                "fees": [],
                "final_price": 10.0,
                "category": "Other",
            }
        ]
    }

    response = client.post(f"/api/receipts/{receipt.id}/save-reviewed-items", json=payload)
    assert response.status_code == 200

    # 3. Verify in DB
    db.refresh(receipt)
    assert receipt.total_amount == 10.0
    assert receipt.items[0].quantity == 1.0
    assert receipt.items[0].price == 10.0  # Unit price = 10 / 1


if __name__ == "__main__":
    test_zero_quantity_save_fix()
