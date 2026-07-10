from app.models import Category, Item, Receipt, ReceiptItem, Store


def test_save_reviewed_categories(client, db):
    # 1. Create temporary receipt
    store = Store(name="Test Store")
    db.add(store)

    # Create History Category and Existing Item
    history_cat = Category(name="Drinks")
    db.add(history_cat)
    db.commit()

    existing_item = Item(name="Old Juice", normalized_name="old juice", category_id=history_cat.id)
    db.add(existing_item)
    db.commit()

    receipt = Receipt(store_id=store.id, status="review", total_amount=15.0)
    db.add(receipt)
    db.commit()

    # 2. Payload for save_reviewed_items
    payload = {
        "items": [
            {
                # Item classified by history: no new category provided, or trying to leave it as is
                "name": "Old Juice",
                "base_price": 5.0,
                "quantity": 1,
                "discounts": [],
                "fees": [],
                "final_price": 5.0,
                # Not providing a category to see if it retains its history one or we can provide the same one
                "category": "",
            },
            {
                # New item that will take the category of Fruit
                "name": "Fresh Apple",
                "base_price": 3.0,
                "quantity": 2,
                "discounts": [],
                "fees": [],
                "final_price": 6.0,
                "category": "Fruit",
            },
            {
                # Existing item where user updates the category
                "name": "Old Juice",
                "base_price": 5.0,
                "quantity": 1,
                "discounts": [],
                "fees": [],
                "final_price": 5.0,
                "category": "Soda",  # Changed from Drinks
            },
        ]
    }

    # 3. Save the reviewed receipt
    response = client.post(f"/api/receipts/{receipt.id}/save-reviewed-items", json=payload)
    assert response.status_code == 200

    # 4. Check the items categories
    # Fetch all items to verify
    db.expire_all()  # Force reload from db

    # "Soda" is not an existing category, so the canonical interceptor
    # funnels it to Beverages instead of creating a new fragment
    updated_juice = db.query(Item).filter(Item.name == "Old Juice").first()
    assert updated_juice is not None
    assert updated_juice.category.name == "Beverages"

    fresh_apple = db.query(Item).filter(Item.name == "Fresh Apple").first()
    assert fresh_apple is not None
    # "Fruit" is likewise intercepted to canonical Produce
    assert fresh_apple.category.name == "Produce"

    # Existing categories — including custom ones like "Drinks" — are still
    # resolvable verbatim: no new "Soda"/"Fruit" fragments were created
    assert db.query(Category).filter(Category.name.in_(["Soda", "Fruit"])).count() == 0

    # Verify ReceiptItems were created
    receipt_items = db.query(ReceiptItem).filter(ReceiptItem.receipt_id == receipt.id).all()
    assert len(receipt_items) == 3
