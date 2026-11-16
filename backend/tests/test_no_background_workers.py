"""Guard on conftest's ``_no_background_workers`` fixture.

The BulkProcessor poll loop, the NutritionEnricher batch and the per-item FDC
enrichment task all open sessions on ``app.database``'s engine from threads
that outlive the request. Under pytest that engine's per-thread connections
were closed underneath those threads, which logged "Cannot operate on a
closed database" and intermittently segfaulted the whole run. These tests
drive the real entry points and fail if any of that work starts again.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.models import Receipt, Store
from app.services.bulk_processor import bulk_processor
from app.services.nutrition_enricher import nutrition_enricher

# start() assigns worker_thread synchronously, so comparing it before and
# after is deterministic even when the thread itself finishes at once.


def test_app_startup_does_not_start_the_bulk_processor():
    before = bulk_processor.worker_thread
    with TestClient(app):
        after = bulk_processor.worker_thread
    assert after is before, "the app lifespan started the BulkProcessor thread"


def test_saving_reviewed_items_starts_no_background_work(client, db):
    store = Store(name="Guard Store")
    db.add(store)
    db.commit()
    receipt = Receipt(store_id=store.id, status="review", total_amount=3.0)
    db.add(receipt)
    db.commit()

    payload = {
        "items": [
            {
                "name": "Plain Oats",
                "base_price": 3.0,
                "quantity": 1,
                "discounts": [],
                "fees": [],
                "final_price": 3.0,
                "category": "Pantry",
            }
        ]
    }

    # A new item with no nutrients puts coverage at 0%, below the catch-up
    # threshold, and has no fdc_match: both triggers fire on the real code.
    before = nutrition_enricher.worker_thread
    with patch("app.services.fdc_service.fdc_service.enrich_db_item") as enrich:
        response = client.post(f"/api/receipts/{receipt.id}/save-reviewed-items", json=payload)
    after = nutrition_enricher.worker_thread

    assert response.status_code == 200
    assert after is before, "the save started the NutritionEnricher thread"
    assert not enrich.called, "the FDC enrichment task ran in the background"
