"""The three price surfaces on the Trends page compared prices in mixed units.

`ReceiptItem.price` is the per-quantity price, which for one item means $/lb on
a weight-priced line and $/package on a packaged one; `ReceiptItem.unit_price`
is worse, because weight-priced rows were written with the package-size divisor
and the column therefore is not a price per unit on every row. Both were being
compared across purchases and across stores.

The store-to-store chart is the one that mattered: its whole job is ranking
retailers, and on the live database it reversed the answer. Russet Potatoes read
cheapest at Safeway ($1.76 against $2.14 and $2.79) when per pound Safeway is
the dearest of the three, at $1.76/lb against $0.60 and $0.74.
"""

from __future__ import annotations

import datetime

import pytest

from app.api.trends import get_inflation_data, get_store_diff, get_store_top_items
from app.models import Category, Item, Receipt, ReceiptItem, Store


@pytest.fixture
def pantry(db):
    category = Category(name="Pantry")
    db.add(category)
    db.commit()
    return category


def _store(db, name):
    s = db.query(Store).filter(Store.name == name).first()
    if not s:
        s = Store(name=name)
        db.add(s)
        db.commit()
    return s


def _item(db, pantry, name):
    i = Item(name=name, normalized_name=name.lower(), category_id=pantry.id)
    db.add(i)
    db.commit()
    return i


def _buy(db, store, item, *, quantity, price, weight=None, unit=None, day=1, unit_price=None):
    receipt = Receipt(
        store_id=store.id,
        status="completed",
        purchase_date=datetime.datetime(2026, 1, day),
        total_amount=price * quantity,
    )
    db.add(receipt)
    db.commit()
    db.add(
        ReceiptItem(
            receipt_id=receipt.id,
            item_id=item.id,
            quantity=quantity,
            price=price,
            weight=weight,
            unit_type=unit,
            unit_price=unit_price,
        )
    )
    db.commit()


class TestTheInflationIndex:
    def test_a_bigger_bag_is_not_a_price_change(self, db, pantry):
        """00 PIZZA FLOUR at a steady $1.75/lb read as a 43% drop."""
        store = _store(db, "Rainbow Grocery")
        flour = _item(db, pantry, "00 PIZZA FLOUR")
        # A 1.75 lb bag for $3.06, then a 1.42 lb bag for $2.49. Both $1.75/lb.
        _buy(db, store, flour, quantity=1.0, price=3.06, weight=1.75, unit="lb", day=1)
        _buy(db, store, flour, quantity=1.42, price=1.7535211, weight=1.42, unit="lb", day=8)

        weeks = get_inflation_data(db=db)

        assert len(weeks) == 1
        assert weeks[0]["count"] == 1
        assert weeks[0]["change"] == pytest.approx(0.0, abs=1.0), (
            f"reported {weeks[0]['change']}% for a price that did not move"
        )

    def test_a_real_rise_still_shows(self, db, pantry):
        store = _store(db, "Rainbow Grocery")
        flour = _item(db, pantry, "00 PIZZA FLOUR")
        _buy(db, store, flour, quantity=1.0, price=2.00, weight=1.0, unit="lb", day=1)
        _buy(db, store, flour, quantity=1.0, price=3.00, weight=1.0, unit="lb", day=8)

        weeks = get_inflation_data(db=db)
        assert weeks[-1]["change"] == pytest.approx(50.0, abs=0.5)

    def test_purchases_on_different_bases_are_not_compared(self, db, pantry):
        """A per-each purchase between two per-lb ones is not a 90% crash."""
        store = _store(db, "Safeway")
        bananas = _item(db, pantry, "BANANA")
        _buy(db, store, bananas, quantity=1.2, price=0.62, weight=1.2, unit="lb", day=1)
        _buy(db, store, bananas, quantity=1.0, price=0.25, day=8)  # one banana, each
        _buy(db, store, bananas, quantity=1.3, price=0.62, weight=1.3, unit="lb", day=15)

        weeks = get_inflation_data(db=db)

        assert sum(w["count"] for w in weeks) == 1, (
            "the per-each purchase was compared to a per-lb one"
        )
        assert weeks[-1]["change"] == pytest.approx(0.0, abs=0.5)

    def test_an_item_bought_once_contributes_nothing(self, db, pantry):
        store = _store(db, "Safeway")
        _buy(db, store, _item(db, pantry, "SAFFRON"), quantity=1.0, price=18.0, day=1)
        assert get_inflation_data(db=db) == []


class TestTheStorePriceHistory:
    def test_the_weekly_price_is_per_unit(self, db, pantry):
        store = _store(db, "Rainbow Grocery")
        flour = _item(db, pantry, "00 PIZZA FLOUR")
        _buy(db, store, flour, quantity=1.0, price=3.06, weight=1.75, unit="lb", day=1)
        _buy(db, store, flour, quantity=1.42, price=1.4788732, weight=1.42, unit="lb", day=15)

        data = get_store_top_items(store=None, store_id=store.id, time_range="all", db=db)
        series = next(d for d in data["datasets"] if d["label"].startswith("00 PIZZA FLOUR"))

        assert series["basis"] == "lb"
        charted = [p for p in series["data"] if p is not None]
        assert charted == [pytest.approx(1.75, abs=0.01), pytest.approx(1.48, abs=0.01)]
        assert 3.06 not in charted

    def test_the_label_states_the_basis(self, db, pantry):
        store = _store(db, "Rainbow Grocery")
        _buy(
            db,
            store,
            _item(db, pantry, "NY STRIP STEAK"),
            quantity=1.0,
            price=10.05,
            weight=1.0,
            unit="lb",
            day=1,
        )
        _buy(db, store, _item(db, pantry, "DATES ORGANIC"), quantity=1.0, price=2.99, day=1)

        labels = {
            d["label"]
            for d in get_store_top_items(store=None, store_id=store.id, time_range="all", db=db)[
                "datasets"
            ]
        }
        assert "NY STRIP STEAK (per lb)" in labels
        assert "DATES ORGANIC (each)" in labels

    def test_two_purchases_in_a_week_average_their_unit_prices(self, db, pantry):
        store = _store(db, "Rainbow Grocery")
        flour = _item(db, pantry, "00 PIZZA FLOUR")
        # Same week: a 2 lb bag at $2/lb and a 1 lb bag at $4/lb -> $3/lb.
        _buy(db, store, flour, quantity=1.0, price=4.00, weight=2.0, unit="lb", day=5)
        _buy(db, store, flour, quantity=1.0, price=4.00, weight=1.0, unit="lb", day=6)

        data = get_store_top_items(store=None, store_id=store.id, time_range="all", db=db)
        series = next(d for d in data["datasets"] if d["label"].startswith("00 PIZZA FLOUR"))
        assert [p for p in series["data"] if p is not None] == [pytest.approx(3.0)]


class TestTheStoreToStoreDiff:
    @pytest.fixture
    def potatoes(self, db, pantry):
        """The live database's Russet Potatoes, with the stored unit_price it has."""
        spuds = _item(db, pantry, "Russet Potatoes, 5 Lb")
        # A 5 lb bag for $3.00 is $0.60/lb; the column says $2.14.
        _buy(
            db,
            _store(db, "Amazon Fresh"),
            spuds,
            quantity=1.0,
            price=3.00,
            weight=5.0,
            unit="lb",
            day=1,
            unit_price=2.14,
        )
        # One loose pound at $1.76; the column agrees, and it is the dearest.
        _buy(
            db,
            _store(db, "Safeway"),
            spuds,
            quantity=1.0,
            price=1.76,
            weight=1.0,
            unit="lb",
            day=2,
            unit_price=1.76,
        )
        # A 5 lb bag for $3.70 is $0.74/lb; the column says $2.79.
        _buy(
            db,
            _store(db, "Whole Foods Market"),
            spuds,
            quantity=1.0,
            price=3.70,
            weight=5.0,
            unit="lb",
            day=3,
            unit_price=2.79,
        )
        return spuds

    def _bar(self, data, store_name, label_starts):
        column = next(i for i, name in enumerate(data["labels"]) if name.startswith(label_starts))
        series = next(d for d in data["datasets"] if d["label"] == store_name)
        return series["data"][column]

    @pytest.mark.usefixtures("potatoes")
    def test_the_cheapest_store_is_the_cheapest_store(self, db):
        data = get_store_diff(db=db)

        amazon = self._bar(data, "Amazon Fresh", "Russet")
        safeway = self._bar(data, "Safeway", "Russet")
        whole_foods = self._bar(data, "Whole Foods Market", "Russet")

        assert amazon == pytest.approx(0.60, abs=0.01)
        assert safeway == pytest.approx(1.76, abs=0.01)
        assert whole_foods == pytest.approx(0.74, abs=0.01)
        assert safeway > amazon and safeway > whole_foods, (
            "the dearest store per pound is still being drawn as the cheapest"
        )

    def test_the_stored_column_would_have_said_the_opposite(self, db, potatoes):
        """Documents the reversal: this is what the chart used to average."""
        stored = {
            line.receipt.store.name: line.unit_price
            for line in db.query(ReceiptItem).filter(ReceiptItem.item_id == potatoes.id)
        }
        assert stored["Safeway"] < stored["Amazon Fresh"] < stored["Whole Foods Market"]

    @pytest.mark.usefixtures("potatoes")
    def test_each_item_label_states_its_basis(self, db):
        assert any(name.endswith("(per lb)") for name in get_store_diff(db=db)["labels"])

    def test_a_store_off_the_basis_gets_no_bar(self, db, pantry):
        """Bananas by the pound at two stores, by the each at a third."""
        bananas = _item(db, pantry, "BANANA")
        for day, (name, price, weight) in enumerate(
            [("Safeway", 0.62, 1.0), ("Whole Foods Market", 1.13, 1.0)], start=1
        ):
            _buy(
                db,
                _store(db, name),
                bananas,
                quantity=1.0,
                price=price,
                weight=weight,
                unit="lb",
                day=day,
            )
        _buy(db, _store(db, "Amazon Fresh"), bananas, quantity=1.0, price=0.99, day=3)

        data = get_store_diff(db=db)
        column = next(i for i, name in enumerate(data["labels"]) if name.startswith("BANANA"))

        assert data["labels"][column] == "BANANA (per lb)"
        amazon = next((d for d in data["datasets"] if d["label"] == "Amazon Fresh"), None)
        assert amazon is None or amazon["data"][column] == 0, (
            "a per-each price is standing next to per-lb prices"
        )
