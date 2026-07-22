import datetime

from app.models import Item, Receipt, ReceiptItem, Store
from app.services.item_matcher import (
    find_similar_items,
    get_best_match,
    get_store_item_ids,
    normalize_item_name,
)


def test_normalize_item_name():
    """Test string normalization for item comparison"""
    assert normalize_item_name("Milk") == "milk"
    assert normalize_item_name("  Organic Eggs  ") == "organic eggs"
    assert normalize_item_name("WHOLE MILK") == "whole milk"
    assert normalize_item_name(None) == ""
    assert normalize_item_name("") == ""


def test_find_similar_items(db):
    """Test fuzzy matching with rapidfuzz"""
    item1 = Item(name="Organic Whole Milk", normalized_name="organic whole milk")
    item2 = Item(name="Eggs Large", normalized_name="eggs large")
    db.add_all([item1, item2])
    db.commit()

    # Should match "Whole Milk Organic" highly due to token_sort_ratio
    matches = find_similar_items("Whole Milk Organic", db, threshold=80)
    assert len(matches) > 0
    assert matches[0]["item"].name == "Organic Whole Milk"
    assert matches[0]["score"] > 80


def test_get_best_match(db):
    """Test getting the single best match"""
    item = Item(name="Gala Apples", normalized_name="gala apples")
    db.add(item)
    db.commit()

    match = get_best_match("apples gala", db, threshold=90)
    assert match is not None
    assert match.name == "Gala Apples"

    # Should not match completely different item
    no_match = get_best_match("Bananas", db, threshold=90)
    assert no_match is None


def test_import_regression():
    """Ensure the app and page routes import cleanly (prevent ImportError regression)"""
    from app.api.pages import review_receipt
    from app.main import app

    # If this test runs, the import chains of app wiring and page routes are valid
    assert review_receipt is not None
    assert app is not None


def _seed_store_history(db, store, items):
    """Create one receipt at the store containing the given items."""
    receipt = Receipt(
        store_id=store.id,
        total_amount=5.0,
        purchase_date=datetime.datetime.now(),
        status="completed",
    )
    db.add(receipt)
    db.commit()
    for item in items:
        db.add(ReceiptItem(receipt_id=receipt.id, item_id=item.id, quantity=1, price=5.0))
    db.commit()
    return receipt


def test_get_store_item_ids(db):
    store_a = Store(name="Store A")
    store_b = Store(name="Store B")
    item = Item(name="Bananas", normalized_name="bananas")
    db.add_all([store_a, store_b, item])
    db.commit()

    _seed_store_history(db, store_a, [item])
    # Second purchase at the same store must not duplicate the id (distinct)
    _seed_store_history(db, store_a, [item])

    assert get_store_item_ids(db, store_a.id) == {item.id}
    assert get_store_item_ids(db, store_b.id) == set()


def test_store_context_breaks_near_ties(db):
    """A same-store item within STORE_CONTEXT_RANK_BOOST points outranks a
    slightly better text match from another store."""
    store = Store(name="Safeway")
    # Raw scores vs "Organic Whole Milk": exact = 100.0, same-store = 92.3
    item_exact = Item(name="Organic Whole Milk", normalized_name="organic whole milk")
    item_store = Item(name="O Organics Whole Milk", normalized_name="o organics whole milk")
    db.add_all([store, item_exact, item_store])
    db.commit()
    _seed_store_history(db, store, [item_store])
    history = get_store_item_ids(db, store.id)

    # Without store context the exact text match wins
    assert get_best_match("Organic Whole Milk", db, threshold=85) is item_exact
    # With store context the previously purchased item wins the near-tie
    assert (
        get_best_match("Organic Whole Milk", db, threshold=85, store_item_ids=history) is item_store
    )


def test_store_context_cannot_close_large_gaps(db):
    """Store history must not override a clearly better text match
    (raw-score gap larger than STORE_CONTEXT_RANK_BOOST)."""
    store = Store(name="Safeway")
    # Raw scores vs "Organic Whole Milk": exact = 100.0, same-store = 83.7
    item_exact = Item(name="Organic Whole Milk", normalized_name="organic whole milk")
    item_store = Item(name="Organic Whole Milk Gallon", normalized_name="organic whole milk gallon")
    db.add_all([store, item_exact, item_store])
    db.commit()
    _seed_store_history(db, store, [item_store])
    history = get_store_item_ids(db, store.id)

    assert (
        get_best_match("Organic Whole Milk", db, threshold=80, store_item_ids=history) is item_exact
    )


def test_store_context_does_not_lower_threshold(db):
    """An item below the threshold stays excluded even with store history —
    ranking context must never promote a weak match into an auto-merge."""
    store = Store(name="Safeway")
    # Raw score vs "Organic Whole Milk" is 71.4 — below the 85 threshold
    item_store = Item(name="Whole Milk", normalized_name="whole milk")
    db.add_all([store, item_store])
    db.commit()
    _seed_store_history(db, store, [item_store])
    history = get_store_item_ids(db, store.id)

    assert find_similar_items("Organic Whole Milk", db, threshold=85, store_item_ids=history) == []
    assert get_best_match("Organic Whole Milk", db, threshold=85, store_item_ids=history) is None


def test_store_context_reports_raw_scores(db):
    """Returned scores are raw text similarity, unchanged by store context."""
    store = Store(name="Safeway")
    item_store = Item(name="O Organics Whole Milk", normalized_name="o organics whole milk")
    db.add_all([store, item_store])
    db.commit()
    _seed_store_history(db, store, [item_store])
    history = get_store_item_ids(db, store.id)

    [without_ctx] = find_similar_items("Organic Whole Milk", db, threshold=85)
    [with_ctx] = find_similar_items("Organic Whole Milk", db, threshold=85, store_item_ids=history)
    assert with_ctx["score"] == without_ctx["score"]
