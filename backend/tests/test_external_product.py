from unittest.mock import MagicMock, patch

from app.models import Item
from app.services.external_product import OpenFoodFactsService

# Mock Data
MOCK_OFF_RESPONSE = {
    "products": [
        {
            "product_name": "Oat Milk",
            "brands": "Oatly",
            "image_url": "http://example.com/oat.jpg",
            "categories": "Plant-based foods, Beverages",
            "code": "123456",
        }
    ]
}


def test_service_search():
    """Test OpenFoodFactsService.search_product parsing"""
    with patch("urllib.request.urlopen") as mock_urlopen:
        # Mock context manager
        mock_response = MagicMock()
        mock_response.read.return_value = import_json().dumps(MOCK_OFF_RESPONSE).encode("utf-8")
        mock_response.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_response

        results = OpenFoodFactsService.search_product("Expected Query")

        assert len(results) == 1
        assert results[0]["product_name"] == "Oat Milk"
        assert results[0]["brand"] == "Oatly"
        assert results[0]["image_url"] == "http://example.com/oat.jpg"


def test_search_endpoint(client):
    """Test GET /api/items/external/search"""
    with patch("app.services.external_product.OpenFoodFactsService.search_product") as mock_search:
        mock_search.return_value = [
            {"product_name": "Mock Product", "image_url": "http://mock.com/img.jpg"}
        ]

        response = client.get("/api/items/external/search?q=test")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["product_name"] == "Mock Product"


def test_update_image_endpoint(client, db):
    """Test PUT /api/items/{id}/image"""
    # Create test item
    item = Item(name="Test Item 123", category_id=None)
    db.add(item)
    db.commit()
    db.refresh(item)

    # The endpoint fetches through safe_fetch, which enforces the scheme,
    # private-range, size, and Content-Type rules before any bytes are read.
    with patch("app.utils.safe_fetch.fetch_remote_image") as mock_fetch:
        mock_fetch.return_value = (b"fake_image_bytes", "jpg")

        # Test request
        payload = {"image_url": "http://example.com/image.jpg"}
        response = client.put(f"/api/items/{item.id}/image", json=payload)

        assert response.status_code == 200
        assert response.json()["success"] is True

        # Verify DB update
        db.refresh(item)
        assert item.image_path is not None
        assert item.image_path.startswith("item_")
        assert item.image_path.endswith(".jpg")


def import_json():
    import json

    return json
