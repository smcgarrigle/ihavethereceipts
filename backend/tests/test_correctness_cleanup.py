import os

import pytest
from fastapi import HTTPException

from app.middleware import CSRFMiddleware
from app.models import Category, Item, Receipt, ReceiptItem, Store


@pytest.mark.asyncio
async def test_csrf_middleware_form_parsing_failure():
    # Setup middleware with dummy ASGI app
    async def dummy_app(_scope, _receive, _send):
        pass

    middleware = CSRFMiddleware(dummy_app)

    # Disable test bypass temporarily
    orig_testing = os.environ.get("TESTING")
    os.environ["TESTING"] = "0"

    try:
        # Construct Request with x-www-form-urlencoded but broken body
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/items/merge",
            "headers": [
                (b"content-type", b"application/x-www-form-urlencoded"),
                (b"cookie", b"csrf_token=test_token"),
            ],
            "session": {"csrf_token": "test_token"},
        }

        async def mock_receive():
            raise RuntimeError("Simulated read/parsing failure")

        from starlette.requests import Request

        request = Request(scope, receive=mock_receive)

        # Should log error and raise HTTP 403 Forbidden with clean detail
        with pytest.raises(HTTPException) as exc_info:
            await middleware.dispatch(request, lambda _req: None)

        assert exc_info.value.status_code == 403
        assert "unable to parse form data" in exc_info.value.detail

    finally:
        if orig_testing is not None:
            os.environ["TESTING"] = orig_testing
        else:
            os.environ.pop("TESTING", None)


def test_save_reviewed_items_transaction_atomicity(client, db, monkeypatch):
    import app.api.receipts_review

    # Setup database records
    store = Store(name="Test Store")
    db.add(store)
    db.commit()

    receipt = Receipt(store_id=store.id, status="review", total_amount=15.0)
    db.add(receipt)

    item = Item(name="Orphaned Item", normalized_name="orphaned item")
    db.add(item)
    db.commit()

    ri = ReceiptItem(receipt_id=receipt.id, item_id=item.id, quantity=1, price=5.0)
    db.add(ri)
    db.commit()

    # Pre-verification: ReceiptItem exists
    assert len(db.query(ReceiptItem).filter(ReceiptItem.receipt_id == receipt.id).all()) == 1

    # Mock get_best_match to raise a runtime error during the loop
    def mock_get_best_match(*_args, **_kwargs):
        raise RuntimeError("Simulated database/logic failure during processing loop")

    monkeypatch.setattr(app.api.receipts_review, "get_best_match", mock_get_best_match)

    payload = {
        "store_name": "New Store Created During Review",
        "items": [
            {
                "name": "Failing Item",
                "base_price": 5.0,
                "quantity": 1,
                "discounts": [],
                "fees": [],
                "final_price": 5.0,
                "category": "New Category Created During Review",
            }
        ],
    }

    # Call endpoint - should return success=False
    response = client.post(f"/api/receipts/{receipt.id}/save-reviewed-items", json=payload)
    assert response.status_code == 200
    assert response.json()["success"] is False

    # Force database session reload
    db.expire_all()

    # Verify that the entire transaction rolled back:
    # 1. New store should NOT exist
    new_store = db.query(Store).filter(Store.name == "New Store Created During Review").first()
    assert new_store is None

    # 2. New category should NOT exist
    new_cat = (
        db.query(Category).filter(Category.name == "New Category Created During Review").first()
    )
    assert new_cat is None

    # 3. The deleted ReceiptItem should still exist
    receipt_items = db.query(ReceiptItem).filter(ReceiptItem.receipt_id == receipt.id).all()
    assert len(receipt_items) == 1


def test_category_concurrency_recovery_direct(db):
    from sqlalchemy.exc import IntegrityError

    # Pre-create category
    cat1 = Category(name="Test Category")
    db.add(cat1)
    db.commit()

    # Simulate concurrency: nested transaction gets unique constraint violation
    category_name = "Test Category"
    category = None

    try:
        with db.begin_nested():
            category = Category(name=category_name)
            db.add(category)
            db.flush()
    except IntegrityError:
        category = db.query(Category).filter(Category.name == category_name).first()

    assert category is not None
    assert category.name == "Test Category"


def test_store_concurrency_recovery_direct(db):
    from sqlalchemy.exc import IntegrityError

    # Pre-create store
    store1 = Store(name="Test Store")
    db.add(store1)
    db.commit()

    # Simulate concurrency: nested transaction gets unique constraint violation
    store_name = "Test Store"
    store = None

    try:
        with db.begin_nested():
            store = Store(name=store_name)
            db.add(store)
            db.flush()
    except IntegrityError:
        store = db.query(Store).filter(Store.name == store_name).first()

    assert store is not None
    assert store.name == "Test Store"
