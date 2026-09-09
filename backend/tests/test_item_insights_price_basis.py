"""The item insights price panel charted the `price` column.

`ReceiptItem.price` is the per-quantity price, and for one item that means two
things: on a weight-priced line the quantity IS the weight, so `price` is
already per pound; on a packaged line the quantity is a count and `price` is
the price of one package. Plotting the column against itself charts how much
was bought, not what it cost — the same defect the X-Ray volatility radar had.

00 PIZZA FLOUR in the live database is the case that showed it here. Three
purchases of the same flour at Rainbow Grocery:

    qty 1.00   price 3.06    weight 1.75 lb  ->  $1.75/lb
    qty 1.42   price 1.7535  weight 1.42 lb  ->  $1.75/lb
    qty 1.42   price 1.4789  weight 1.42 lb  ->  $1.48/lb

The sparkline drew 3.06 -> 1.75 -> 1.48, a 52% collapse, where the price per
pound went 1.75 -> 1.75 -> 1.48. The first point was the cost of a bigger bag.
"""

from __future__ import annotations

import datetime
import json
import re

import pytest

from app.models import Category, Item, Receipt, ReceiptItem, Store
from app.services.spend import comparable_price_series, price_basis_label


@pytest.fixture
def store(db):
    s = Store(name="Rainbow Grocery")
    db.add(s)
    db.commit()
    return s


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


def _flour(db, store):
    """The live database's three 00 PIZZA FLOUR purchases, to the cent."""
    flour = _item(db, "00 PIZZA FLOUR")
    _purchase(db, store, flour, quantity=1.0, price=3.06, weight=1.75, unit="lb", day=1)
    _purchase(db, store, flour, quantity=1.42, price=1.7535211, weight=1.42, unit="lb", day=2)
    _purchase(db, store, flour, quantity=1.42, price=1.4788732, weight=1.42, unit="lb", day=3)
    return flour


def _charted(html):
    """The prices the sparkline is actually drawn from, oldest first."""
    match = re.search(r"const points = (\[.*?\]);", html, re.DOTALL)
    assert match, "the insights page did not emit a price series"
    return json.loads(match.group(1))


class TestComparablePriceSeries:
    def test_the_dominant_basis_wins(self, db, store):
        steak = _item(db, "NY STRIP STEAK")
        for day, price in enumerate([20.0, 22.0, 24.0], start=1):
            _purchase(db, store, steak, quantity=1.0, price=price, weight=1.0, unit="lb", day=day)
        _purchase(db, store, steak, quantity=1.0, price=99.0, day=9)

        lines = db.query(ReceiptItem).filter(ReceiptItem.item_id == steak.id).all()
        basis, series = comparable_price_series(lines)
        assert basis == "lb"
        assert [price for _, price in series] == [20.0, 22.0, 24.0]

    def test_a_tie_breaks_on_the_basis_name(self, db, store):
        """Two bases, one purchase each — the answer must not depend on row order."""
        thing = _item(db, "BIO TUB")
        _purchase(db, store, thing, quantity=1.0, price=5.0, weight=8.0, unit="oz", day=1)
        _purchase(db, store, thing, quantity=1.0, price=6.0, day=2)

        lines = db.query(ReceiptItem).filter(ReceiptItem.item_id == thing.id).all()
        assert comparable_price_series(lines)[0] == "each"
        assert comparable_price_series(list(reversed(lines)))[0] == "each"

    def test_the_order_given_is_the_order_returned(self, db, store):
        flour = _flour(db, store)
        lines = (
            db.query(ReceiptItem)
            .filter(ReceiptItem.item_id == flour.id)
            .order_by(ReceiptItem.id.desc())
            .all()
        )
        _, series = comparable_price_series(lines)
        assert [line.id for line, _ in series] == [line.id for line in lines]

    def test_unpriced_lines_are_not_a_series(self, db, store):
        ghost = _item(db, "FREE SAMPLE")
        _purchase(db, store, ghost, quantity=1.0, price=0.0, day=1)
        lines = db.query(ReceiptItem).filter(ReceiptItem.item_id == ghost.id).all()
        assert comparable_price_series(lines) == ("", [])

    def test_nothing_at_all(self):
        assert comparable_price_series([]) == ("", [])

    @pytest.mark.parametrize(
        ("basis", "expected"),
        [("lb", "per lb"), ("fl oz", "per fl oz"), ("each", "each"), ("", "each")],
    )
    def test_the_basis_is_said_one_way(self, basis, expected):
        assert price_basis_label(basis) == expected


class TestTheSparkline:
    def test_the_flour_case(self, db, client, store):
        """The reported bug, with the live database's own numbers."""
        flour = _flour(db, store)

        points = _charted(client.get(f"/items/{flour.id}/insights").text)

        assert [p["price"] for p in points] == [
            pytest.approx(1.7486, abs=0.001),
            pytest.approx(1.7535, abs=0.001),
            pytest.approx(1.4789, abs=0.001),
        ], "the sparkline is plotting the price column, not the price per pound"
        assert 3.06 not in [p["price"] for p in points], "a bigger bag is not a higher price"

    def test_the_chart_is_read_oldest_first(self, db, client, store):
        flour = _flour(db, store)
        points = _charted(client.get(f"/items/{flour.id}/insights").text)
        assert [p["label"] for p in points] == ["Jan 01, 2026", "Jan 02, 2026", "Jan 03, 2026"]

    def test_the_summary_strip_is_on_the_same_basis(self, db, client, store):
        flour = _flour(db, store)

        html = client.get(f"/items/{flour.id}/insights").text

        assert "Price per lb" in html
        # $1.48 to $1.75 a pound, not $1.48 to $3.06 a line.
        assert "$1.48" in html and "$1.75" in html
        assert re.search(r"Highest[^$]*\$3\.06", html, re.DOTALL) is None

    def test_a_card_states_the_price_and_its_unit(self, db, client, store):
        """$0.94 an ounce and $21.69 a pound are not otherwise distinguishable."""
        flour = _flour(db, store)

        html = client.get(f"/items/{flour.id}/insights").text

        # The 1.75 lb bag cost $3.06 in total and $1.75 per pound.
        assert "$3.06" in html
        assert "$1.75 per lb" in html

    def test_purchases_on_another_basis_are_declared_not_dropped(self, db, client, store):
        cukes = _item(db, "CUCUMBER PERSIAN")
        for day, price in enumerate([2.99, 3.49], start=1):
            _purchase(db, store, cukes, quantity=1.0, price=price, weight=1.0, unit="lb", day=day)
        _purchase(db, store, cukes, quantity=1.0, price=0.79, day=3)

        html = client.get(f"/items/{cukes.id}/insights").text

        assert len(_charted(html)) == 2
        assert "Excludes 1 purchase bought in another unit" in html
        assert "(3 purchases)" in html, "the timeline should still show every purchase"

    def test_an_item_with_no_weight_charts_each(self, db, client, store):
        brush = _item(db, "ORAL B TOOTH")
        for day, price in enumerate([4.0, 6.7, 9.4], start=1):
            _purchase(db, store, brush, quantity=1.0, price=price, day=day)

        html = client.get(f"/items/{brush.id}/insights").text

        assert [p["price"] for p in _charted(html)] == [4.0, 6.7, 9.4]
        assert "Price each" in html
        assert "Excludes" not in html

    def test_a_quantity_of_two_is_two_of_a_price_not_one(self, db, client, store):
        """A packaged line: the card shows the $6.20 paid and the $3.10 each."""
        crackers = _item(db, "Baked Whole Grain Bread")
        _purchase(db, store, crackers, quantity=2.0, price=3.10, day=1)

        html = client.get(f"/items/{crackers.id}/insights").text

        assert "$6.20" in html
        assert "$3.10 each" in html

    def test_an_item_never_bought_still_renders(self, db, client):
        orphan = _item(db, "NEVER BOUGHT")
        resp = client.get(f"/items/{orphan.id}/insights")
        assert resp.status_code == 200
        assert "const points" not in resp.text
