"""Guards on the FDC enrichment scheduled from the receipt review save.

The task used to be scheduled as ``add_task(fdc_service.enrich_db_item, db,
item.id)`` *before* ``db.add(item)`` and ``db.flush()``, so ``item.id`` was
still None when it was captured. Every new item enriched against
``Item.id == None``, matched nothing, and returned silently — automatic
nutrition enrichment had never run for a reviewed item.

A second defect sat on the same line: the request-scoped session was handed to
the task, and FastAPI tears down yield dependencies before background tasks
run, so the session would already be closed even with a correct id.
"""

from unittest.mock import patch

import pytest

from app.models import Item, Receipt, Store


@pytest.fixture
def receipt(db):
    store = Store(name="Test Store")
    db.add(store)
    db.commit()

    receipt = Receipt(store_id=store.id, status="review", total_amount=8.0)
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt


def _payload(name: str = "Greek Yogurt"):
    return {
        "items": [
            {
                "name": name,
                "base_price": 4.0,
                "quantity": 2,
                "discounts": [],
                "fees": [],
                "final_price": 8.0,
                "category": "Dairy",
            }
        ]
    }


def test_enrichment_is_scheduled_with_a_real_item_id(client, db, receipt):
    """The scheduled task must carry the item's assigned primary key."""
    with patch("app.services.fdc_service.enrich_db_item_task") as mock_task:
        response = client.post(f"/api/receipts/{receipt.id}/save-reviewed-items", json=_payload())

    assert response.status_code == 200

    item = db.query(Item).filter(Item.name == "Greek Yogurt").first()
    assert item is not None and item.id is not None

    assert mock_task.called, (
        "No enrichment task ran for a new item — nothing will ever fill in "
        "USDA nutrients, GTIN, or ingredients for it."
    )
    scheduled_id = mock_task.call_args.args[0]
    assert scheduled_id is not None, (
        "The task was scheduled with item.id of None, which happens when the "
        "id is read before db.flush() assigns it."
    )
    assert scheduled_id == item.id


def test_task_is_not_handed_the_request_session(client, receipt):
    """The task must take an id only, and open its own session."""
    with patch("app.services.fdc_service.enrich_db_item_task") as mock_task:
        client.post(f"/api/receipts/{receipt.id}/save-reviewed-items", json=_payload("Oat Milk"))

    assert mock_task.called
    for arg in list(mock_task.call_args.args) + list(mock_task.call_args.kwargs.values()):
        assert not hasattr(arg, "query"), (
            "A Session was passed into the background task. Request-scoped "
            "sessions are closed before background tasks run."
        )


def test_no_enrichment_scheduled_when_the_user_pinned_an_fdc_match(client, db, receipt):
    """An explicit match is authoritative — don't spend an API call re-deriving it."""
    payload = _payload("Cheddar")
    payload["items"][0]["fdc_match"] = {"fdc_id": "173410", "gtin": "0001234567890"}

    with patch("app.services.fdc_service.enrich_db_item_task") as mock_task:
        response = client.post(f"/api/receipts/{receipt.id}/save-reviewed-items", json=payload)

    assert response.status_code == 200
    assert not mock_task.called

    item = db.query(Item).filter(Item.name == "Cheddar").first()
    assert item is not None
    assert str(item.fdc_id) == "173410"


def test_task_wrapper_opens_and_closes_its_own_session():
    """enrich_db_item_task must not need a caller-supplied session."""
    from app.services import fdc_service as fdc_module

    seen = {}

    def fake_enrich(session, item_id):
        seen["session"] = session
        seen["item_id"] = item_id
        return True

    with (
        patch.object(fdc_module.fdc_service, "enrich_db_item", side_effect=fake_enrich),
        patch("app.database.SessionLocal") as mock_factory,
    ):
        assert fdc_module.enrich_db_item_task(42) is True

    assert seen["item_id"] == 42
    assert mock_factory.called, "The task did not open its own session"
    mock_factory.return_value.close.assert_called_once()
