import json
from datetime import datetime

from app.models import Category, Item, Receipt, ReceiptItem, Store


def test_ocr_auto_tuning(client, db):
    # Setup Store
    store = Store(name="Test Store")
    db.add(store)

    # Setup Category
    cat = Category(name="Beverages")
    db.add(cat)
    db.commit()

    # Setup Parent Item
    parent_item = Item(name="NA Beer 6-pack", normalized_name="na beer 6-pack", category_id=cat.id)
    db.add(parent_item)
    db.commit()

    # Setup Historical ReceiptItem to learn overrides from
    hist_receipt = Receipt(store_id=store.id, purchase_date=datetime.now(), total_amount=10.0)
    db.add(hist_receipt)
    db.commit()

    hist_ri = ReceiptItem(
        receipt_id=hist_receipt.id,
        item_id=parent_item.id,
        quantity=6.0,
        weight=72.0,
        unit_type="fl oz",
        price=1.5,
    )
    db.add(hist_ri)
    db.commit()

    # Now create a new OCR Receipt that matches the name exactly but with weird casing
    ocr_data = {
        "items": [
            {
                "name": "NA BEER 6-PACK",
                "base_price": 9.0,
            },
            {"name": "Very Unique OCR Item", "base_price": 4.0},
        ],
        "store_name": "Test Store",
        "total_amount": 13.0,
    }

    new_receipt = Receipt(
        store_id=store.id,
        purchase_date=datetime.now(),
        total_amount=13.0,
        ocr_data=json.dumps(ocr_data),
        status="completed",
    )
    db.add(new_receipt)
    db.commit()

    # Call the review endpoint which triggers main.py data prep
    response = client.get(f"/receipts/{new_receipt.id}/review")
    assert response.status_code == 200

    text = response.text

    # The JSON data is injected into the HTML. Let's verify our injected keys exist.

    # Feature 2 Check: Auto-merge
    assert '"auto_merged": true' in text

    # Original OCR Name preserved
    assert '"original_ocr_name": "NA BEER 6-PACK"' in text

    # Feature 3 Check: Inherited Historical Overrides
    assert '"quantity": 6.0' in text
    assert '"weight": 72.0' in text
    assert '"unit_type": "fl oz"' in text
    assert '"history_applied": true' in text

    # Feature 1 Check: Inherited Parent Category
    assert '"category": "Beverages"' in text

    # Output name verification
    assert '"name": "NA Beer 6-pack"' in text

    # Fallback to AI categories for unknown item
    assert '"name": "Very Unique OCR Item"' in text
    assert '"category":' in text  # Ensure the category key was added
