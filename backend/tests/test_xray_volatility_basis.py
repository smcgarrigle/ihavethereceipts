"""The price volatility radar compared prices in different units.

`ReceiptItem.price` is the per-quantity price, and for one item that can mean
two things: on a weight-priced line the quantity IS the weight, so `price` is
already per pound; on a packaged line the quantity is a count and `price` is per
package. The radar appended `price` for every purchase and compared them, so
what it measured was how much was bought, not what it cost.

RED INSTANT YEAST in the live database is the case that showed it — five
purchases of the same bulk yeast between $10.06 and $11.00 a pound, reported as
a 260.8% swing where the real one is 9.1%. Regular Gasoline was worse: 226.3%
against a true 3.8% a gallon, and only after `gal`/`gallon`/`gallons` are
treated as one unit, since it was bought once under each spelling.
"""

from __future__ import annotations

import datetime

import pytest

from app.api.xray import receipt_xray_data
from app.models import Category, Item, Receipt, ReceiptItem, Store
from app.services.spend import comparable_unit_price
from app.utils.item_parsing import normalise_unit


@pytest.fixture
def store(db):
    s = Store(name="Rainbow Grocery")
    db.add(s)
    db.commit()
    return s


def _purchase(db, store, item, *, quantity, price, weight=None, unit=None, day=1):
    r = Receipt(
        store_id=store.id,
        status="completed",
        purchase_date=datetime.datetime(2026, 1, day),
        total_amount=price * quantity,
    )
    db.add(r)
    db.commit()
    db.add(
        ReceiptItem(
            receipt_id=r.id,
            item_id=item.id,
            quantity=quantity,
            price=price,
            weight=weight,
            unit_type=unit,
        )
    )
    db.commit()


def _item(db, name):
    category = db.query(Category).filter(Category.name == "Pantry").first()
    if not category:
        category = Category(name="Pantry")
        db.add(category)
        db.commit()
    i = Item(name=name, normalized_name=name.lower(), category_id=category.id)
    db.add(i)
    db.commit()
    return i


def _radar(db):
    return {row["name"]: row for row in receipt_xray_data(db=db)["price_volatility"]}


class TestNormaliseUnit:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("gal", "gal"),
            ("gallon", "gal"),
            ("gallons", "gal"),
            ("GALLONS", "gal"),
            ("lbs", "lb"),
            ("Pound", "lb"),
            ("ounce", "oz"),
            ("fl_oz", "fl oz"),
            ("each", "each"),
            ("", "each"),
            (None, "each"),
            ("oz", "oz"),
        ],
    )
    def test_spellings_collapse(self, raw, expected):
        assert normalise_unit(raw) == expected


class TestComparableUnitPrice:
    def test_the_weight_priced_shape(self, db):
        """quantity IS the weight, so price is already per pound."""
        item = _item(db, "Bulk Yeast")
        row = ReceiptItem(
            item_id=item.id, quantity=0.16, price=10.0625, weight=0.16, unit_type="lb"
        )
        assert comparable_unit_price(row) == (pytest.approx(10.0625), "lb")

    def test_the_packaged_shape(self, db):
        """quantity is a count, so price is per package and must be divided."""
        item = _item(db, "Packet Yeast")
        row = ReceiptItem(item_id=item.id, quantity=1.0, price=1.41, weight=0.14, unit_type="lb")
        price, basis = comparable_unit_price(row)
        assert basis == "lb"
        assert price == pytest.approx(10.07, abs=0.01)

    def test_no_weight_falls_back_to_each(self):
        row = ReceiptItem(quantity=2.0, price=3.5, weight=None, unit_type=None)
        assert comparable_unit_price(row) == (pytest.approx(3.5), "each")

    def test_a_zero_weight_falls_back_to_each(self):
        row = ReceiptItem(quantity=2.0, price=3.5, weight=0.0, unit_type="oz")
        assert comparable_unit_price(row) == (pytest.approx(3.5), "each")

    def test_unit_each_with_a_weight_stays_each(self):
        row = ReceiptItem(quantity=2.0, price=3.5, weight=1.0, unit_type="each")
        assert comparable_unit_price(row) == (pytest.approx(3.5), "each")


class TestTheRadar:
    def test_the_yeast_case(self, db, store):
        """The reported bug, with the live database's own numbers."""
        yeast = _item(db, "RED INSTANT YEAST")
        # One weight-priced purchase, four packaged ones — all ~$10/lb.
        _purchase(db, store, yeast, quantity=0.16, price=10.0625, weight=0.16, unit="lb", day=1)
        _purchase(db, store, yeast, quantity=1.0, price=1.41, weight=0.14, unit="lb", day=2)
        _purchase(db, store, yeast, quantity=1.0, price=1.31, weight=0.13, unit="lb", day=3)
        _purchase(db, store, yeast, quantity=1.0, price=1.76, weight=0.16, unit="lb", day=4)
        _purchase(db, store, yeast, quantity=1.0, price=2.24, weight=0.22, unit="lb", day=5)

        row = _radar(db)["RED INSTANT YEAST"]
        assert row["basis"] == "lb"
        assert row["count"] == 5
        assert row["spread_pct"] < 20, f"still reporting quantity variance: {row['spread_pct']}%"
        assert row["avg"] == pytest.approx(10.28, abs=0.05)

    def test_one_unit_spelled_three_ways_is_one_series(self, db, store):
        """Regular Gasoline was bought once as gal, once gallon, once gallons."""
        fuel = _item(db, "Regular Gasoline")
        _purchase(db, store, fuel, quantity=10.0, price=5.30, weight=10.0, unit="gal", day=1)
        _purchase(db, store, fuel, quantity=12.0, price=5.35, weight=12.0, unit="gallon", day=2)
        _purchase(db, store, fuel, quantity=9.0, price=5.40, weight=9.0, unit="gallons", day=3)

        row = _radar(db)["Regular Gasoline"]
        assert row["basis"] == "gal"
        assert row["count"] == 3, "the three spellings did not collapse into one series"
        assert row["spread_pct"] < 5

    def test_an_item_with_no_weight_reports_each(self, db, store):
        brush = _item(db, "ORAL B TOOTH")
        for day, price in enumerate([4.0, 6.7, 9.4], start=1):
            _purchase(db, store, brush, quantity=1.0, price=price, day=day)

        row = _radar(db)["ORAL B TOOTH"]
        assert row["basis"] == "each"
        assert row["spread_pct"] > 50, "genuine per-item volatility should survive"

    def test_the_dominant_basis_wins(self, db, store):
        """Mixed bases: compare the one with the most purchases, not both."""
        steak = _item(db, "NY STRIP STEAK")
        for day, price in enumerate([20.0, 22.0, 24.0], start=1):
            _purchase(db, store, steak, quantity=1.0, price=price, weight=1.0, unit="lb", day=day)
        _purchase(db, store, steak, quantity=1.0, price=99.0, day=9)
        _purchase(db, store, steak, quantity=1.0, price=1.0, day=10)

        row = _radar(db)["NY STRIP STEAK"]
        assert row["basis"] == "lb"
        assert row["count"] == 3, "the per-each purchases leaked into the per-lb series"

    def test_fewer_than_three_on_the_dominant_basis_is_dropped(self, db, store):
        sparse = _item(db, "Rare Thing")
        _purchase(db, store, sparse, quantity=1.0, price=5.0, weight=1.0, unit="lb", day=1)
        _purchase(db, store, sparse, quantity=1.0, price=6.0, weight=1.0, unit="lb", day=2)
        assert "Rare Thing" not in _radar(db)

    def test_every_row_declares_its_basis(self, db, store):
        thing = _item(db, "Some Thing")
        for day, price in enumerate([1.0, 2.0, 3.0], start=1):
            _purchase(db, store, thing, quantity=1.0, price=price, day=day)
        for row in receipt_xray_data(db=db)["price_volatility"]:
            assert row["basis"], f"{row['name']} has no basis"
