"""A pack size is not a unit of measure.

The backfill recovered weights from item names, so "SIERRA NEVADA Golden 6pk
Cans" gained weight=6, unit_type="pk". The price derived from that is the price
of one can — right number — but it was labelled "per pk", which reads as the
price of the whole six-pack, about six times the figure.

"each" is not available for it either: that label already means one whole thing
as bought, which is what the same item's un-counted lines are measured in. So a
count unit is said as "per unit", and keeps a basis of its own so the two never
land in one series.
"""

from __future__ import annotations

import pytest

from app.models import ReceiptItem
from app.services.spend import comparable_price_series, comparable_unit_price, price_basis_label
from app.utils.item_parsing import COUNT_UNITS


class TestTheLabel:
    @pytest.mark.parametrize("basis", sorted(COUNT_UNITS))
    def test_every_count_unit_is_said_as_per_unit(self, basis):
        assert price_basis_label(basis) == "per unit"

    @pytest.mark.parametrize(
        ("basis", "expected"),
        [
            ("lb", "per lb"),
            ("oz", "per oz"),
            ("fl oz", "per fl oz"),
            ("gal", "per gal"),
            ("pt", "per pt"),  # pint is a measure, not a count
            ("each", "each"),
            ("", "each"),
        ],
    )
    def test_measures_are_unchanged(self, basis, expected):
        assert price_basis_label(basis) == expected

    def test_the_six_pack_case(self):
        """$11.00 for a 6pk is $1.83 a can — never $1.83 for the pack."""
        line = ReceiptItem(quantity=1.0, price=11.0, weight=6.0, unit_type="pk")
        price, basis = comparable_unit_price(line)

        assert price == pytest.approx(1.83, abs=0.01)
        assert f"${price:.2f} {price_basis_label(basis)}" == "$1.83 per unit"

    def test_the_egg_case(self):
        line = ReceiptItem(quantity=1.0, price=3.42, weight=18.0, unit_type="ct")
        price, basis = comparable_unit_price(line)

        assert price == pytest.approx(0.19, abs=0.01)
        assert price_basis_label(basis) == "per unit"


class TestTheBasisStaysDistinct:
    def test_a_count_basis_is_not_the_each_basis(self):
        """Same label would be fine; the same *basis* would mix $1.83 with $11.00."""
        packed = ReceiptItem(quantity=1.0, price=11.0, weight=6.0, unit_type="pk")
        loose = ReceiptItem(quantity=1.0, price=11.0, weight=None, unit_type=None)

        assert comparable_unit_price(packed)[1] == "pk"
        assert comparable_unit_price(loose)[1] == "each"

    def test_the_two_are_never_charted_together(self):
        """365 Large Brown Eggs carries both shapes in the live database."""
        lines = [
            ReceiptItem(id=1, quantity=1.0, price=3.42, weight=18.0, unit_type="ct"),
            ReceiptItem(id=2, quantity=1.0, price=3.60, weight=18.0, unit_type="ct"),
            ReceiptItem(id=3, quantity=1.0, price=3.99, weight=None, unit_type=None),
        ]

        basis, series = comparable_price_series(lines)

        assert basis == "ct"
        assert [line.id for line, _ in series] == [1, 2]
        assert all(price < 1 for _, price in series), "a carton price leaked into a per-egg series"
