import json

import pytest
from bs4 import BeautifulSoup

from app.models.category import Category
from app.models.receipt import Receipt


@pytest.fixture
def dummy_receipt(db):
    """Creates a dummy receipt for testing pages that require a receipt ID."""
    receipt = Receipt(
        total_amount=10.00,
        status="completed",
        ocr_data=json.dumps({"items": [], "store_name": "Test Store"}),
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt


@pytest.fixture
def dummy_category(db):
    """Creates a dummy category for testing."""
    category = Category(name="Produce")
    db.add(category)
    db.commit()
    return category


def test_dashboard_integrity(client):
    """Verify critical IDs on the Dashboard."""
    response = client.get("/")
    assert response.status_code == 200
    soup = BeautifulSoup(response.text, "html.parser")

    # Chart & Modal IDs
    expected_ids = [
        "store-history-modal",
        "modal-title",
        "storeHistoryChart",
        "category-store-modal",
        "drilldown-modal-title",
        "drilldown-modal-content",
        "categoryTrendsChart",
        "trendsLoadingIndicator",
        "trends-legend",
    ]
    for element_id in expected_ids:
        assert soup.find(id=element_id) is not None, f"Missing {element_id} on Dashboard"


def test_receipts_page_integrity(client):
    """Verify critical IDs on the Receipts page."""
    response = client.get("/receipts")
    assert response.status_code == 200
    soup = BeautifulSoup(response.text, "html.parser")

    expected_ids = [
        "receipt-file",
        "upload-result",
        "receipts-container",
        "stores-data",
        "manual-modal-title",
    ]
    for element_id in expected_ids:
        assert soup.find(id=element_id) is not None, f"Missing {element_id} on Receipts page"


def test_items_page_integrity(client):
    """Verify critical IDs on the Items page."""
    response = client.get("/items")
    assert response.status_code == 200
    soup = BeautifulSoup(response.text, "html.parser")

    expected_ids = [
        "duplicates-list",
        "search-results",
        "relevantReceiptsModal",
        "relevant-receipts-list",
    ]
    for element_id in expected_ids:
        assert soup.find(id=element_id) is not None, f"Missing {element_id} on Items page"


def test_receipt_review_integrity(client, dummy_receipt):
    """Verify critical IDs on the Receipt Review page."""
    response = client.get(f"/receipts/{dummy_receipt.id}/review")
    assert response.status_code == 200
    soup = BeautifulSoup(response.text, "html.parser")

    expected_ids = ["ocr-data", "detection-alert", "modal-title"]
    for element_id in expected_ids:
        assert soup.find(id=element_id) is not None, f"Missing {element_id} on Review page"


def test_produce_mode_integrity(client):
    """Verify critical IDs on the Produce Mode page."""
    response = client.get("/produce")
    assert response.status_code == 200
    soup = BeautifulSoup(response.text, "html.parser")

    # Produce mode relies heavily on x-data, but we check for the app root
    assert soup.find(attrs={"x-data": "produceEntryApp()"}) is not None
