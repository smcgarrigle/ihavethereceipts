from datetime import datetime

from bs4 import BeautifulSoup

from app.models import Category, Item, Receipt, ReceiptItem, Store


def test_trends_nutrition_page_integrity(client):
    """Verify presence of Tufte-inspired nutrition elements on Trends page."""
    response = client.get("/trends")
    assert response.status_code == 200
    soup = BeautifulSoup(response.text, "html.parser")

    expected_ids = [
        "calorieProfileChart",
        "cal-split-fat",
        "cal-split-sugar",
        "cal-split-protein",
        "avg-fat",
        "avg-sugar",
        "avg-protein",
        "avg-sodium",
        "target-fat",
        "chart-sm-sodium",
        "chart-sm-fat",
        "chart-sm-sugar",
        "chart-sm-protein",
        "nutritionChart",  # Collapsible detail
        "nutrition-normalization-badge",
        "nutrition-normalization-text",
    ]
    for element_id in expected_ids:
        assert soup.find(id=element_id) is not None, f"Missing {element_id} on Trends page"


def test_trends_all_charts_fragment(client, db):
    """Verify the all-charts API fragment delivers the new nutrition metrics."""
    # Seed a Store first
    store = Store(name="Whole Foods")
    db.add(store)
    db.commit()
    db.refresh(store)

    # Seed a Category
    category = Category(name="Dairy")
    db.add(category)
    db.commit()
    db.refresh(category)

    # Seed a basic item with nutrients
    item = Item(
        name="Organic Milk",
        category_id=category.id,
        nutrients={
            "calories_100g": 150.0,
            "fat_100g": 8.0,
            "sugar_100g": 12.0,
            "protein_100g": 8.0,
            "sodium_100g": 50.0,
        },
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    # Seed a receipt
    receipt = Receipt(
        store_id=store.id, purchase_date=datetime(2026, 6, 1), total_amount=5.00, status="completed"
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)

    # Seed a receipt item (1000g of milk -> nutrients scaled by 10)
    receipt_item = ReceiptItem(
        receipt_id=receipt.id,
        item_id=item.id,
        quantity=1.0,
        price=5.00,
        unit_price=5.00,
        weight=1000.0,
    )
    db.add(receipt_item)
    db.commit()

    response = client.get("/api/trends/fragment/all-charts?time_range=6m")
    assert response.status_code == 200

    # The response is an HTML fragment containing scripts
    # Check that updateAllCharts call has the correct key structures
    assert "calorie_profile" in response.text
    assert "nutrition_multiples" in response.text
    assert "nutrition_density" in response.text
    assert "weekly" in response.text
    assert "usda" in response.text
