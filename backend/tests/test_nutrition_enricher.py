from unittest.mock import patch

from app.models import Category, Item
from app.models.nutrition_suggestion import NutritionSuggestion
from app.services.nutrition_enricher import NutritionEnricher, get_enrichable_coverage


def test_nutrition_enricher_suggestion_creation(db):
    # Create test data
    category = Category(name="Produce")
    db.add(category)
    db.commit()

    item = Item(name="Apple", normalized_name="apple", category_id=category.id, nutrients=None)
    db.add(item)
    db.commit()

    # Create enricher instance
    enricher = NutritionEnricher()

    # Mock fdc_service
    mock_fdc_data = {
        "fdc_id": 123456,
        "description": "Apple, raw",
        "brand": "TestBrand",
        "category": "Fruits",
        "gtin": "123456789",
        "serving_size": 100,
        "serving_unit": "g",
        "ingredients": "Apples",
        "nutrients": {"sugars_100g": 10.0},
    }

    with patch(
        "app.services.nutrition_enricher.fdc_service.enrich_item_data", return_value=mock_fdc_data
    ):
        with patch(
            "app.services.nutrition_enricher.fdc_service._clean_query", return_value="apple"
        ):
            with patch("time.sleep", return_value=None):  # Skip 4s sleep in tests
                with patch("app.services.nutrition_enricher.SessionLocal", return_value=db):
                    with patch.object(db, "close"):
                        enricher._run_batch(batch_size=10)

    # Assert that a suggestion was created
    suggestion = (
        db.query(NutritionSuggestion).filter(NutritionSuggestion.item_id == item.id).first()
    )
    assert suggestion is not None
    assert suggestion.fdc_id == 123456
    assert suggestion.fdc_description == "Apple, raw"
    assert suggestion.match_score > 0
    assert suggestion.nutrients == {"sugars_100g": 10.0}
    assert suggestion.status == "pending"


def test_enrichable_coverage_exclusion(db):
    # Add a food item with nutrients
    cat_food = Category(name="Pantry")
    db.add(cat_food)
    db.commit()

    item_food = Item(
        name="Rice",
        normalized_name="rice",
        category_id=cat_food.id,
        nutrients={"carbohydrates_100g": 80.0},
    )
    db.add(item_food)

    # Add an excluded category item (should be ignored by coverage math)
    cat_fees = Category(name="Fees & Taxes")
    db.add(cat_fees)
    db.commit()

    item_fee = Item(
        name="Bottle Deposit",
        normalized_name="bottle deposit",
        category_id=cat_fees.id,
        nutrients=None,
    )
    db.add(item_fee)
    db.commit()

    coverage = get_enrichable_coverage(db)

    # Coverage should be 100% because the fee item is excluded from the denominator
    assert coverage == 100.0
