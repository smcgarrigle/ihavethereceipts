"""Tests for PDF/Image viewer modal auto-focus and escape key handling."""

from app.models.receipt import Receipt
from app.models.store import Store


def _create_sample_receipt(db) -> Receipt:
    store = Store(name="Test Mart")
    db.add(store)
    db.flush()

    receipt = Receipt(
        store_id=store.id,
        total_amount=10.50,
        status="approved",
        image_path="/path/to/receipt.pdf",
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt


def test_receipt_review_modal_has_autofocus_and_escape(db, client):
    """The receipt review page modal must have autofocus ref on close button and tabindex=-1 on embed."""
    receipt = _create_sample_receipt(db)
    resp = client.get(f"/receipts/{receipt.id}/review")
    assert resp.status_code == 200

    html = resp.text
    # Check that close button has x-ref="closeBtn" and Esc hint
    assert 'x-ref="closeBtn"' in html
    assert "focusClose" in html
    # Check that embed has tabindex="-1" to prevent trapping focus
    assert 'tabindex="-1"' in html
    # Check escape key handler
    assert "@keydown.escape" in html


def test_receipts_page_modal_has_autofocus_and_escape(client):
    """The receipts list page modal must have autofocus ref on close button and tabindex=-1 on embed."""
    resp = client.get("/receipts")
    assert resp.status_code == 200

    html = resp.text
    assert 'x-ref="closeBtn"' in html
    assert "focusClose" in html
    assert 'tabindex="-1"' in html
    assert "@keydown.escape" in html
