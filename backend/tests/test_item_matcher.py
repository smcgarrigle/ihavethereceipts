from app.models import Item
from app.services.item_matcher import (
    find_similar_items,
    get_best_match,
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
