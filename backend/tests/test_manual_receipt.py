from app.models import Receipt


def test_create_manual_receipt(client, db):
    """Test creating a manual receipt without an image"""
    payload = {
        "store_name": "Farmer's Market",
        "purchase_date": "2023-10-27",
        "total_amount": 45.50,
        "notes": "Fresh veggies",
    }

    response = client.post("/api/receipts/manual", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "receipt_id" in data

    # Verify DB
    receipt = db.query(Receipt).filter(Receipt.id == data["receipt_id"]).first()
    assert receipt is not None
    assert receipt.store.name == "Farmer's Market"
    assert receipt.total_amount == 45.50
    assert receipt.image_path is None
    assert receipt.notes == "Fresh veggies"
    assert "manual_entry" in receipt.ocr_data


def test_manual_receipt_defaults(client, db):
    """Test defaults for manual receipt"""
    payload = {"store_name": "Quick Stop"}

    response = client.post("/api/receipts/manual", json=payload)
    assert response.status_code == 200

    receipt = db.query(Receipt).filter(Receipt.id == response.json()["receipt_id"]).first()
    assert receipt.total_amount == 0.0
    receipt = db.query(Receipt).filter(Receipt.id == response.json()["receipt_id"]).first()
    assert receipt.total_amount == 0.0
    assert receipt.purchase_date is not None  # Should be today


def test_save_items_to_manual_receipt(client, db):
    """Test saving reviewed items to a manual receipt"""
    # 1. Create manual receipt
    payload = {"store_name": "Test Market"}
    create_res = client.post("/api/receipts/manual", json=payload)
    receipt_id = create_res.json()["receipt_id"]

    # 2. Add Items
    items_payload = {
        "items": [
            {
                "name": "Manual Apple",
                "base_price": 0.50,
                "final_price": 0.50,
                "quantity": 2,
                "unit_price": 0.25,
                "unit_type": "lb",
                "category": "Produce",
                "discounts": [],
                "fees": [],
            },
            {
                "name": "Manual Bread",
                "base_price": 3.00,
                "final_price": 3.00,
                "quantity": 1,
                "category": "Bakery",
                "discounts": [],
                "fees": [],
            },
        ]
    }

    save_res = client.post(f"/api/receipts/{receipt_id}/save-reviewed-items", json=items_payload)
    assert save_res.status_code == 200
    assert save_res.json()["success"] is True
    assert save_res.json()["items_saved"] == 2

    # 3. Verify in DB
    from app.models import ReceiptItem

    items = db.query(ReceiptItem).filter(ReceiptItem.receipt_id == receipt_id).all()
    assert len(items) == 2

    apple = next(i for i in items if i.item.name == "Manual Apple")
    assert apple.price == 0.25  # price per unit
    assert apple.quantity == 2
    assert apple.item.category.name == "Produce"
