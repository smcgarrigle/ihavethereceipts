"""Tests for the manual FDC match override (PUT /api/items/{id}/fdc)."""

from unittest.mock import patch

from app.api.items import _parse_fdc_ref
from app.models import Item

FOUNDATION_FOOD = {
    "fdcId": 2003586,
    "description": "Flour, 00",
    "dataType": "Foundation",
    "foodNutrients": [
        {"nutrient": {"number": "203", "name": "Protein", "unitName": "g"}, "amount": 11.4},
        {
            "nutrient": {"number": "204", "name": "Total lipid (fat)", "unitName": "g"},
            "amount": 1.52,
        },
        {
            "nutrient": {
                "number": "205",
                "name": "Carbohydrate, by difference",
                "unitName": "g",
            },
            "amount": 74.4462,
        },
    ],
}


def _make_item(db, **kwargs):
    item = Item(name="00 Pizza Flour", normalized_name="00 pizza flour", **kwargs)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


class TestParseFdcRef:
    def test_plain_url(self):
        assert _parse_fdc_ref("https://fdc.nal.usda.gov/food-details/2003586/nutrients") == 2003586

    def test_fdc_app_hash_url(self):
        assert (
            _parse_fdc_ref("https://fdc.nal.usda.gov/fdc-app.html#/food-details/2003586/nutrients")
            == 2003586
        )

    def test_bare_id(self):
        assert _parse_fdc_ref(" 2003586 ") == 2003586

    def test_garbage(self):
        assert _parse_fdc_ref("not a url") is None
        assert _parse_fdc_ref("") is None


class TestManualOverrideEndpoint:
    def test_override_sets_match_and_nutrients(self, client, db):
        item = _make_item(db, fdc_id=1111, nutrients={"proteins_100g": 1.0})

        with patch(
            "app.services.fdc_service.fdc_service.get_food_details",
            return_value=FOUNDATION_FOOD,
        ):
            resp = client.put(
                f"/api/items/{item.id}/fdc",
                json={"fdc_ref": "https://fdc.nal.usda.gov/food-details/2003586/nutrients"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["fdc_id"] == 2003586
        assert body["description"] == "Flour, 00"

        db.refresh(item)
        assert item.fdc_id == 2003586
        assert item.fdc_override is True
        # Manual pin replaces canonical nutrients with the chosen food's values
        assert item.nutrients["proteins_100g"] == 11.4

    def test_override_preserves_custom_nutrients(self, client, db):
        item = _make_item(db, custom_nutrients={"calories": 380})

        with patch(
            "app.services.fdc_service.fdc_service.get_food_details",
            return_value=FOUNDATION_FOOD,
        ):
            resp = client.put(f"/api/items/{item.id}/fdc", json={"fdc_ref": "2003586"})

        assert resp.status_code == 200
        db.refresh(item)
        assert item.custom_nutrients == {"calories": 380}
        assert item.effective_nutrients["calories"] == 380

    def test_bad_ref_rejected(self, client, db):
        item = _make_item(db)
        resp = client.put(f"/api/items/{item.id}/fdc", json={"fdc_ref": "not a url"})
        assert resp.status_code == 400
        assert "FDC ID" in resp.json()["detail"]

    def test_fdc_fetch_failure_surfaces(self, client, db):
        item = _make_item(db)
        with patch("app.services.fdc_service.fdc_service.get_food_details", return_value=None):
            resp = client.put(f"/api/items/{item.id}/fdc", json={"fdc_ref": "2003586"})
        assert resp.status_code == 502
        db.refresh(item)
        assert item.fdc_override is False

    def test_missing_item_404(self, client):
        resp = client.put("/api/items/999999/fdc", json={"fdc_ref": "2003586"})
        assert resp.status_code == 404

    def test_clear_resets_override(self, client, db):
        item = _make_item(db, fdc_id=2003586, fdc_override=True)
        resp = client.delete(f"/api/items/{item.id}/fdc")
        assert resp.status_code == 200
        db.refresh(item)
        assert item.fdc_id is None
        assert item.fdc_override is False


class TestEnrichmentRespectsOverride:
    def test_propagation_skips_pinned_items(self, db):
        """Auto-enrichment of one item must not clobber another item's manual pin."""
        from app.services.fdc_service import fdc_service

        target = _make_item(db)
        pinned = Item(
            name="00 Pizza Flour Blue Bag",
            normalized_name="00 pizza flour blue bag",
            fdc_id=2003586,
            fdc_override=True,
        )
        db.add(pinned)
        db.commit()

        enriched = {
            "fdc_id": 5555,
            "description": "Some Branded Flour",
            "brand": "Brand",
            "category": None,
            "gtin": "0001112223334",
            "serving_size": None,
            "serving_unit": None,
            "ingredients": None,
            "nutrients": {},
        }
        with patch.object(fdc_service, "enrich_item_data", return_value=enriched):
            assert fdc_service.enrich_db_item(db, target.id) is True

        db.refresh(target)
        db.refresh(pinned)
        assert target.fdc_id == 5555
        # The similarly-named pinned item keeps its manual match
        assert pinned.fdc_id == 2003586
        assert pinned.fdc_override is True
