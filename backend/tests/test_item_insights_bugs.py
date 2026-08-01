"""Tests for item insights page and nutrition search — reproduce bugs on item #62.

Bug 1: search_foods() method does not exist on FDCService (should be search_items).
Bug 2: String-typed custom_nutrients cause Jinja2 |round filter crash.
"""

from app.models.category import Category
from app.models.item import Item


def _make_item_with_string_nutrients(db):
    """Create an item with string-typed custom_nutrients (like item #62)."""
    cat = Category(name="Beverages")
    db.add(cat)
    db.flush()

    item = Item(
        name="Test NA Beer",
        normalized_name="test na beer",
        category_id=cat.id,
        custom_nutrients={
            "calories": "70",
            "fat": "0",
            "carbohydrates": "17",
            "sugars": "2",
            "protein": "2",
        },
        nutrition_source="auto",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


class TestSearchFoodsMethodExists:
    """Bug 1: fdc_service.search_foods() does not exist."""

    def test_search_foods_method_not_on_fdc_service(self):
        """Verify the bug: search_foods is called but doesn't exist."""
        from app.services.fdc_service import fdc_service

        assert not hasattr(fdc_service, "search_foods"), (
            "search_foods unexpectedly exists — if this was added, "
            "the call site in items.py line 435 is now valid."
        )
        assert hasattr(
            fdc_service, "search_items"
        ), "search_items should be the correct method name."

    def test_nutrition_search_endpoint_does_not_crash(self, db, client):
        """The /api/items/{id}/nutrition/search endpoint should not crash."""
        item = _make_item_with_string_nutrients(db)

        resp = client.get(f"/api/items/{item.id}/nutrition/search?q=beer")
        # Before fix: crashes with AttributeError: 'FDCService' has no attribute 'search_foods'
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True


class TestStringNutrientsPageLoad:
    """Bug 2: String-typed custom_nutrients crash the insights page template."""

    def test_insights_page_loads_with_string_nutrients(self, db, client):
        """Item insights page should render even when custom_nutrients has string values."""
        item = _make_item_with_string_nutrients(db)

        resp = client.get(f"/items/{item.id}/insights")
        # Before fix: crashes in Jinja2 with TypeError on |round filter for string '70'
        assert resp.status_code == 200
        assert b"Nutrition Facts" in resp.content or b"No Nutrition Data Found" in resp.content
