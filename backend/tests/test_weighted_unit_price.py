"""Guards for the unit_price convention (audit finding 09).

``ReceiptItem.unit_price`` is the price of ONE unit of ``unit_type`` — items.py
normalises it straight to $/oz (``up / 16.0`` when unit_type is "lb"), so a
per-package figure stored there is overstated by the package size.

Two writers have to agree on that: ``_map_schema`` in the OCR pass, and the
save-reviewed-items endpoint, which fills in a weight of its own.
"""

from app.models import Item, Receipt, ReceiptItem, Store
from app.services.ocr import _map_schema
from app.utils.item_parsing import weighted_unit_price


class TestWeightedUnitPriceHelper:
    def test_packaged_divides_out_quantity(self):
        # Three 15 oz cans of beans for $3.87 — the audit's example.
        assert weighted_unit_price(3.87, 3, 15.0) == 0.086

    def test_single_package(self):
        # "RUSSET POT 5LB" at $3.99 → $0.798/lb.
        assert weighted_unit_price(3.99, 1, 5.0) == 0.798

    def test_bulk_weight_is_the_total_bought(self):
        # 10.756 gal of gasoline at $57.01: quantity IS the weight, so the line
        # total is already spread across it. Dividing by qty * weight would
        # report $0.49/gal for $5.30/gal fuel.
        assert weighted_unit_price(57.01, 10.756, 10.756, is_bulk=True) == 5.3003

    def test_no_weight_is_none(self):
        assert weighted_unit_price(3.87, 3, None) is None
        assert weighted_unit_price(3.87, 3, 0) is None

    def test_zero_quantity_falls_back_to_one(self):
        assert weighted_unit_price(3.99, 0, 5.0) == 0.798


class TestMapSchemaSizeExtraction:
    def test_multi_quantity_size_in_name(self):
        """Size parsed out of the name: quantity must be divided out too."""
        data = _map_schema(
            {
                "items": [
                    {
                        "name": "BEANS 15OZ",
                        "final_price": 3.87,
                        "base_price": 3.87,
                        "quantity": 3,
                    }
                ]
            }
        )
        item = data["items"][0]
        assert item["weight"] == 15.0
        assert item["unit_type"] == "oz"
        # Pre-fix this was 3.87 / 15 = 0.258 — three times too high.
        assert item["unit_price"] == 0.086

    def test_size_in_name_does_not_make_a_can_bulk(self):
        """is_bulk means weight-priced, not 'a size was parsed out of the name'."""
        data = _map_schema({"items": [{"name": "BEANS 15OZ", "final_price": 3.87, "quantity": 3}]})
        assert data["items"][0].get("is_bulk") is not True

    def test_model_supplied_weight_divides_out_quantity(self):
        """The same bug sat in the branch for model-supplied weights."""
        data = _map_schema(
            {
                "items": [
                    {
                        "name": "Kombucha",
                        "final_price": 4.96,
                        "quantity": 2,
                        "weight": 16.0,
                        "unit_type": "fl oz",
                    }
                ]
            }
        )
        item = data["items"][0]
        # Pre-fix: 4.96 / 16 = 0.31, double the true $0.155/fl oz.
        assert item["unit_price"] == 0.155
        assert item.get("is_bulk") is not True

    def test_model_supplied_weight_priced_line_is_left_alone(self):
        """A real "@ $2.49/lb" line: weight is the total bought, not a package."""
        data = _map_schema(
            {
                "items": [
                    {
                        "name": "Bananas",
                        "final_price": 4.98,
                        "quantity": 2.0,
                        "weight": 2.0,
                        "unit_type": "lb",
                        "is_bulk": True,
                    }
                ]
            }
        )
        assert data["items"][0]["unit_price"] == 2.49

    def test_name_without_size_keeps_per_item_price(self):
        data = _map_schema({"items": [{"name": "Just an item", "final_price": 6.0, "quantity": 2}]})
        item = data["items"][0]
        assert item["unit_price"] == 3.0
        assert not item.get("weight")


class TestReviewSaveStoresPerWeightUnitPrice:
    def test_weight_extracted_at_review_recomputes_unit_price(self, client, db):
        """extract_weight fills in a weight the OCR pass never saw.

        It does not strip the size from the name, which is why 900 of the 984
        wrong rows in the live database still carry their size — the weight
        landed in the column while unit_price stayed per-package.
        """
        store = Store(name="Test Store")
        db.add(store)
        receipt = Receipt(store_id=store.id, status="review", total_amount=6.2)
        db.add(receipt)
        db.commit()

        payload = {
            "items": [
                {
                    "name": "Bob's Red Mill Wheat Germ, 12 oz",
                    "base_price": 6.2,
                    "final_price": 6.2,
                    "quantity": 2,
                    "unit_price": 3.1,  # what the client sends: per package
                    "discounts": [],
                    "fees": [],
                    "category": "Pantry",
                }
            ]
        }
        resp = client.post(f"/api/receipts/{receipt.id}/save-reviewed-items", json=payload)
        assert resp.status_code == 200

        db.expire_all()
        ri = db.query(ReceiptItem).filter(ReceiptItem.receipt_id == receipt.id).one()
        assert ri.weight == 12.0
        assert ri.unit_type == "oz"
        # price stays the per-quantity price spend is read from.
        assert round(ri.price, 2) == 3.10
        # Pre-fix unit_price was stored as 3.1 — items.py then reported
        # $3.10/oz for a jar that costs $0.258/oz.
        assert ri.unit_price == 0.2583

    def test_weight_priced_line_keeps_its_per_pound_price(self, client, db):
        """A bulk line must not be divided by its weight twice."""
        store = Store(name="Test Store")
        db.add(store)
        receipt = Receipt(store_id=store.id, status="review", total_amount=4.98)
        db.add(receipt)
        db.commit()

        payload = {
            "items": [
                {
                    "name": "Bananas",
                    "base_price": 4.98,
                    "final_price": 4.98,
                    "quantity": 2.0,
                    "weight": 2.0,
                    "unit_type": "lb",
                    "is_bulk": True,
                    "unit_price": 2.49,
                    "discounts": [],
                    "fees": [],
                    "category": "Produce",
                }
            ]
        }
        resp = client.post(f"/api/receipts/{receipt.id}/save-reviewed-items", json=payload)
        assert resp.status_code == 200

        db.expire_all()
        ri = db.query(ReceiptItem).filter(ReceiptItem.receipt_id == receipt.id).one()
        assert ri.unit_price == 2.49

    def test_no_weight_keeps_the_client_unit_price(self, client, db):
        store = Store(name="Test Store")
        db.add(store)
        receipt = Receipt(store_id=store.id, status="review", total_amount=6.0)
        db.add(receipt)
        db.commit()

        payload = {
            "items": [
                {
                    "name": "Sponge",
                    "base_price": 6.0,
                    "final_price": 6.0,
                    "quantity": 2,
                    "unit_price": 3.0,
                    "discounts": [],
                    "fees": [],
                    "category": "Household",
                }
            ]
        }
        resp = client.post(f"/api/receipts/{receipt.id}/save-reviewed-items", json=payload)
        assert resp.status_code == 200

        db.expire_all()
        ri = db.query(ReceiptItem).filter(ReceiptItem.receipt_id == receipt.id).one()
        assert ri.weight is None
        assert ri.unit_price == 3.0
        assert db.query(Item).filter(Item.name == "Sponge").first() is not None


class TestQuantityEqualsWeightIsWeightPriced:
    """A loose-produce line the model forgot to flag as bulk.

    Replaying the corpus turned up "CUCUMBER PERSIAN", quantity 0.88 and weight
    0.88 lb with is_bulk unset — dividing by quantity * weight there reports
    $4.42/lb for a $3.89/lb cucumber.
    """

    def test_fractional_quantity_matching_weight(self):
        assert weighted_unit_price(3.42, 0.88, 0.88) == 3.8864

    def test_quantity_one_is_unambiguous(self):
        # qty == weight == 1: both readings agree.
        assert weighted_unit_price(7.19, 1.0, 1.0) == 7.19

    def test_map_schema_leaves_unflagged_loose_produce_alone(self):
        data = _map_schema(
            {
                "items": [
                    {
                        "name": "CUCUMBER PERSIAN",
                        "final_price": 3.42,
                        "quantity": 0.88,
                        "weight": 0.88,
                        "unit_type": "lb",
                    }
                ]
            }
        )
        assert data["items"][0]["unit_price"] == 3.8864
