import html
import threading

from app.models import Category, Item, Receipt, ReceiptItem, Store
from app.services.ocr import get_daily_usage, increment_daily_usage


def test_security_headers_and_csp(client):
    """Test that all security headers and Content Security Policy are present in responses."""
    response = client.get("/")
    assert response.status_code == 200

    headers = response.headers
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    csp = headers.get("Content-Security-Policy")
    assert csp is not None
    assert "default-src 'self'" in csp
    # Self-contained since the precompiled Tailwind build: no external hosts
    assert "https://" not in csp
    assert "font-src 'self' data:" in csp
    # Alpine.js expression evaluation still requires unsafe-eval
    assert "'unsafe-eval'" in csp


def test_content_length_limit_middleware(client):
    """Test that requests exceeding 15MB are rejected with 413 Payload Too Large."""
    # Send a request with Content-Length larger than 15MB
    large_headers = {"Content-Length": str(16 * 1024 * 1024)}  # 16MB
    response = client.post("/api/receipts/upload", headers=large_headers, data=b"a" * 100)
    assert response.status_code == 413
    assert "Payload too large" in response.text


def test_search_query_truncation(client, db):
    """Test that items search query parameter q is truncated to 100 characters."""
    # Add dummy item to search
    item = Item(name="ShortName", normalized_name="shortname")
    db.add(item)
    db.commit()

    # Search with very long query
    long_q = "ShortName" + "a" * 150
    response = client.get(f"/api/items/search?q={long_q}")
    assert response.status_code == 200
    # The truncated query "ShortName" + "a" * 91 won't match, which is fine,
    # but the server should process it successfully without error.
    assert "Type at least 2 characters" not in response.text


def test_category_normalization_on_create(client, db):
    """Test that categories created via API are normalized (trim, title-case, length limits)."""
    payload = {"name": "  pROduce  "}
    response = client.post("/api/categories/create", json=payload)
    assert response.status_code == 200
    assert response.json()["success"] is True

    # Check database
    cat = db.query(Category).filter(Category.name == "Produce").first()
    assert cat is not None

    # Test length restriction
    long_name = "a" * 100
    payload_long = {"name": long_name}
    response_long = client.post("/api/categories/create", json=payload_long)
    assert response_long.status_code == 200

    normalized_name = (long_name[:50]).title()
    cat_long = db.query(Category).filter(Category.name == normalized_name).first()
    assert cat_long is not None


def test_category_normalization_on_receipt_save(client, db):
    """Test that category names are normalized when saving reviewed receipt items."""
    store = Store(name="Test Store")
    db.add(store)
    db.commit()

    receipt = Receipt(store_id=store.id, status="review", total_amount=10.00)
    db.add(receipt)
    db.commit()

    payload = {
        "store_name": "Test Store",
        "items": [
            {
                "name": "Organic Apples",
                "base_price": 5.00,
                "quantity": 1,
                "discounts": [],
                "fees": [],
                "final_price": 5.00,
                "category": "   fReSh pRoDuCe   ",
            }
        ],
    }

    response = client.post(f"/api/receipts/{receipt.id}/save-reviewed-items", json=payload)
    assert response.status_code == 200
    assert response.json()["success"] is True

    # The unknown name is normalized AND intercepted into the canonical
    # taxonomy — "fresh produce" resolves to Produce, no fragment created
    cat = db.query(Category).filter(Category.name == "Produce").first()
    assert cat is not None
    assert db.query(Category).filter(Category.name == "Fresh Produce").first() is None


def test_html_escaping_in_responses(client, db):
    """Test that dynamic item/store names containing HTML/JS tags are escaped in HTMLResponse output."""
    # 1. Escape store_name in delete_receipt response
    store = Store(name="<script>alert('store')</script>")
    db.add(store)
    db.commit()

    receipt = Receipt(store_id=store.id, status="review", total_amount=12.34)
    db.add(receipt)
    db.commit()

    # Call delete endpoint
    response = client.delete(f"/api/receipts/{receipt.id}")
    assert response.status_code == 200

    expected_escaped_store = html.escape("<script>alert('store')</script>")
    assert expected_escaped_store in response.text
    assert "<script>alert('store')</script>" not in response.text

    # 2. Escape item.name in get_receipt_items endpoint
    item = Item(
        name="<script>alert('item')</script>", normalized_name="<script>alert('item')</script>"
    )
    db.add(item)
    db.commit()

    receipt2 = Receipt(store_id=store.id, status="saved", total_amount=5.00)
    db.add(receipt2)
    db.commit()

    ri = ReceiptItem(receipt_id=receipt2.id, item_id=item.id, quantity=1, price=5.00)
    db.add(ri)
    db.commit()

    response2 = client.get(f"/api/receipts/{receipt2.id}/items")
    assert response2.status_code == 200

    expected_escaped_item = html.escape("<script>alert('item')</script>")
    assert expected_escaped_item in response2.text
    assert "<script>alert('item')</script>" not in response2.text


def test_ocr_usage_tracker_thread_safety(monkeypatch, tmp_path):
    """Test that OCR daily usage cache functions are thread-safe and can run concurrently."""
    # Point USAGE_TRACKER_FILE to a temporary path to avoid modifying production data
    temp_file = tmp_path / "ocr_usage.json"
    import app.services.ocr

    monkeypatch.setattr(app.services.ocr, "USAGE_TRACKER_FILE", temp_file)

    def run_increment():
        for _ in range(20):
            increment_daily_usage()
            get_daily_usage()

    threads = []
    for _ in range(5):
        t = threading.Thread(target=run_increment)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # Expect total increments = 5 * 20 = 100
    assert get_daily_usage() == 100


def test_demo_data_population_and_clearing(db):
    """Test that demo data is populated and cleared successfully."""
    from app.models import Item, Receipt
    from app.services.onboarding import clear_demo_data, populate_demo_data

    # Ensure starts clean
    db.query(Receipt).filter(Receipt.notes == "DEMO_DATA").delete()
    db.commit()

    initial_item_count = db.query(Item).count()

    # Populate
    success = populate_demo_data(db)
    assert success is True

    # Check that demo receipts were created
    demo_receipts = db.query(Receipt).filter(Receipt.notes == "DEMO_DATA").all()
    assert len(demo_receipts) == 3

    # Clear
    clear_success = clear_demo_data(db)
    assert clear_success is True

    # Check they are gone
    demo_receipts_after = db.query(Receipt).filter(Receipt.notes == "DEMO_DATA").all()
    assert len(demo_receipts_after) == 0

    # Orphans should be deleted
    assert db.query(Item).count() == initial_item_count


def test_html_escaping_in_items_and_categories_pages(client, db):
    """Test that items and categories names are HTML escaped when listed."""
    # Create malicious item and category
    malicious_cat = Category(name="<script>alert('bad-cat')</script>")
    db.add(malicious_cat)
    db.flush()

    malicious_item = Item(
        name="<script>alert('bad-item')</script>",
        normalized_name="bad-item-normal",
        category_id=malicious_cat.id,
    )
    db.add(malicious_item)
    db.flush()

    store = Store(name="Test Store")
    db.add(store)
    db.flush()

    receipt = Receipt(store_id=store.id, status="completed", total_amount=10.0)
    db.add(receipt)
    db.flush()

    ri = ReceiptItem(receipt_id=receipt.id, item_id=malicious_item.id, quantity=1, price=10.0)
    db.add(ri)
    db.commit()

    # Get items list
    resp_items = client.get("/api/items/list")
    assert resp_items.status_code == 200
    assert html.escape(malicious_item.name) in resp_items.text
    assert malicious_item.name not in resp_items.text

    # Get categories list
    resp_cats = client.get("/api/categories/list")
    assert resp_cats.status_code == 200
    assert html.escape(malicious_cat.name) in resp_cats.text
    assert malicious_cat.name not in resp_cats.text
