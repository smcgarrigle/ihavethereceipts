"""Audit finding 14: the reviewed total discarded tax and overrode the user.

The save wrote `request.total_amount`, then overwrote it with the sum of the
line items whenever any priced item existed. Tax is not normally a line item,
so a receipt of $50.10 of items and $4.22 of tax stored $50.10 no matter what
the user typed, with no way to make the correction stick.

The audit says it overwrites "unconditionally". It does not — there is an
`item_sum > 0` guard, and the fallback chain behind it is deliberate. The
substance holds; the code is less careless than the wording implies.
"""

from __future__ import annotations

import pytest

from app.models import Receipt, ReceiptItem, Store
from app.services.spend import unaccounted


def _receipt(db, total=0.0):
    store = db.query(Store).filter(Store.name == "Tax Test").first()
    if not store:
        store = Store(name="Tax Test")
        db.add(store)
        db.commit()
    r = Receipt(store_id=store.id, status="review", total_amount=total)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _items(*prices):
    return [
        {
            "name": f"Item {i}",
            "base_price": p,
            "final_price": p,
            "quantity": 1,
            "discounts": [],
            "fees": [],
            "category": "Pantry",
        }
        for i, p in enumerate(prices)
    ]


def _saved_total(db, receipt_id) -> float:
    db.expire_all()
    return float(db.query(Receipt).filter(Receipt.id == receipt_id).one().total_amount)


class TestUnaccountedHelper:
    @pytest.mark.parametrize(
        ("total", "item_sum", "expected"),
        [
            (54.32, 50.10, 4.22),  # sales tax
            (50.10, 50.10, 0.0),  # nothing unexplained
            (40.00, 50.00, -10.0),  # items over-collected
            (None, 50.00, 0.0),  # nothing to compare
            (50.00, 0.0, 0.0),  # no items
            (50.004, 50.00, 0.0),  # float noise, below the one-cent floor
        ],
    )
    def test_it(self, total, item_sum, expected):
        assert unaccounted(total, item_sum) == pytest.approx(expected)


class TestTheUserTotalSticks:
    def test_tax_is_not_discarded(self, client, db):
        """The finding, exactly: $50.10 of items and $4.22 of tax."""
        r = _receipt(db)
        resp = client.post(
            f"/api/receipts/{r.id}/save-reviewed-items",
            json={"total_amount": 54.32, "items": _items(20.05, 30.05)},
        )
        assert resp.status_code == 200
        assert _saved_total(db, r.id) == pytest.approx(54.32), "the tax was overwritten"

    def test_the_correction_survives_a_second_save(self, client, db):
        r = _receipt(db)
        body = {"total_amount": 54.32, "items": _items(20.05, 30.05)}
        client.post(f"/api/receipts/{r.id}/save-reviewed-items", json=body)
        client.post(f"/api/receipts/{r.id}/save-reviewed-items", json=body)
        assert _saved_total(db, r.id) == pytest.approx(54.32)

    def test_a_total_below_the_item_sum_is_still_honoured(self, client, db):
        """A parse that over-collected: the user's total is still the total."""
        r = _receipt(db)
        client.post(
            f"/api/receipts/{r.id}/save-reviewed-items",
            json={"total_amount": 40.00, "items": _items(20.05, 30.05)},
        )
        assert _saved_total(db, r.id) == pytest.approx(40.00)


class TestTheFallbacksStillHold:
    def test_no_total_supplied_falls_back_to_the_items(self, client, db):
        r = _receipt(db)
        client.post(
            f"/api/receipts/{r.id}/save-reviewed-items",
            json={"items": _items(20.05, 30.05)},
        )
        assert _saved_total(db, r.id) == pytest.approx(50.10)

    def test_a_zero_total_never_clobbers_a_good_one(self, client, db):
        r = _receipt(db)
        client.post(
            f"/api/receipts/{r.id}/save-reviewed-items",
            json={"total_amount": 0, "items": _items(20.05, 30.05)},
        )
        assert _saved_total(db, r.id) == pytest.approx(50.10)

    def test_items_are_unaffected(self, client, db):
        r = _receipt(db)
        client.post(
            f"/api/receipts/{r.id}/save-reviewed-items",
            json={"total_amount": 54.32, "items": _items(20.05, 30.05)},
        )
        db.expire_all()
        lines = db.query(ReceiptItem).filter(ReceiptItem.receipt_id == r.id).all()
        assert len(lines) == 2
        assert sum(float(line.price) for line in lines) == pytest.approx(50.10)


class TestTheListShowsIt:
    def _save(self, client, db, total, *prices):
        r = _receipt(db)
        client.post(
            f"/api/receipts/{r.id}/save-reviewed-items",
            json={"total_amount": total, "items": _items(*prices)},
        )
        return r

    def test_the_stored_total_is_displayed_not_the_item_sum(self, client, db):
        self._save(client, db, 54.32, 20.05, 30.05)
        body = client.get("/api/receipts/list").text
        assert "$54.32" in body
        assert "$50.10" not in body, "the list recomputed the total from the items"

    def test_the_gap_is_named(self, client, db):
        self._save(client, db, 54.32, 20.05, 30.05)
        assert "includes $4.22 not in the item list" in client.get("/api/receipts/list").text

    def test_over_collected_items_are_flagged(self, client, db):
        self._save(client, db, 40.00, 20.05, 30.05)
        body = client.get("/api/receipts/list").text
        assert "items add up to $10.10 more than this total" in body

    def test_an_exact_match_says_nothing(self, client, db):
        self._save(client, db, 50.10, 20.05, 30.05)
        body = client.get("/api/receipts/list").text
        assert "not in the item list" not in body
        assert "more than this total" not in body

    def test_a_receipt_with_no_items_still_shows_its_total(self, client, db):
        r = _receipt(db, total=12.34)
        db.commit()
        body = client.get("/api/receipts/list").text
        assert "$12.34" in body
        assert str(r.id)
