from app.models import Category, Item


def test_read_items(client, db):
    # Create category and item
    cat = Category(name="Dairy")
    db.add(cat)
    db.commit()

    item = Item(name="Milk", category_id=cat.id)
    db.add(item)
    db.commit()

    # Add receipt item so it shows up (purchase_count > 0)
    from app.models import Receipt, ReceiptItem

    receipt = Receipt(store_id=1, total_amount=10.0)
    db.add(receipt)
    db.flush()
    ri = ReceiptItem(receipt_id=receipt.id, item_id=item.id, price=3.50)
    db.add(ri)
    db.commit()

    response = client.get("/api/items/list")
    assert response.status_code == 200
    assert "Milk" in response.text
    assert "Dairy" in response.text


def test_items_categorization(client, db):
    """Test items without category show as Uncategorized"""
    item = Item(name="Unknown Thing")
    db.add(item)
    db.commit()

    # Add receipt item
    from app.models import Receipt, ReceiptItem

    receipt = Receipt(store_id=1, total_amount=5.0)
    db.add(receipt)
    db.flush()
    ri = ReceiptItem(receipt_id=receipt.id, item_id=item.id, price=1.50)
    db.add(ri)
    db.commit()

    response = client.get("/api/items/list")
    assert response.status_code == 200
    assert "Unknown Thing" in response.text
    assert "Uncategorized" in response.text
