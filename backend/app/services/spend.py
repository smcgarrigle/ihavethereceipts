"""One definition of what a receipt line cost.

``ReceiptItem.price`` is the per-quantity price and the line total is
``price * quantity`` (see DATA_DESIGN.md). That expression was re-derived at
thirty-five call sites, and re-deriving it went wrong in both directions: some
dashboards read the per-unit ``price`` as though it were already the line total
and understated spend by the quantity factor, while others divided the
already-per-unit ``price`` by quantity a second time and reported a habit change
from one unit to four as a 75% price drop.

The column's meaning is correct and documented. What it needed was one place to
say it, so import from here rather than writing the multiplication again.
"""

import json
from typing import Any

from app.models import ReceiptItem
from app.utils.item_parsing import (
    is_weight_priced,
    normalise_unit,
    weighted_unit_price,
)

# SQL-side line total, for use inside func.sum(...), order_by(...) and friends.
# SQLAlchemy expressions are reusable, so this one constant serves every query.
LINE_TOTAL = ReceiptItem.price * ReceiptItem.quantity


def line_total(receipt_item: Any) -> float:
    """What one receipt line actually cost, in dollars."""
    return float(receipt_item.price or 0.0) * float(receipt_item.quantity or 0.0)


def line_total_of(price: Any, quantity: Any) -> float:
    """Line total from a price/quantity pair pulled straight out of a query row."""
    return float(price or 0.0) * float(quantity or 0.0)


def unit_price_of(price: Any, _quantity: Any = None) -> float:
    """The per-unit price of a line.

    ``price`` already *is* the per-unit figure — the quantity is accepted so
    call sites read explicitly rather than looking like they forgot it. Dividing
    by quantity here is the mirror-image bug this module exists to stop.
    """
    return float(price or 0.0)


def unaccounted(total: float | None, item_sum: float) -> float:
    """What a receipt's total carries beyond its line items, to the cent.

    Normally sales tax, which is not a line item: the reviewed total used to be
    overwritten with the item sum, so a receipt of $50.10 of items and $4.22 of
    tax stored $50.10 whatever the user typed.

    Positive means tax or fees the items do not account for. Negative means the
    parsed items add up to more than the receipt says, which is a sign the parse
    over-collected rather than a sign about the shopping. Returns 0.0 when the
    two agree, or when there is nothing to compare.

    Measured over the 413 receipts in the live database: 296 agree exactly, 83
    carry a positive gap (median +$5.68, smallest +$0.20 — comfortably above
    float noise, hence the one-cent floor), and 12 are negative.
    """
    if not total or item_sum <= 0:
        return 0.0
    diff = round(float(total) - item_sum, 2)
    return diff if abs(diff) >= 0.01 else 0.0


def comparable_unit_price(receipt_item: Any) -> tuple[float, str]:
    """A price that can be compared across purchases, and the basis it is in.

    ``price`` is the per-quantity price, and for the same item that can mean two
    different things: on a weight-priced line the quantity IS the weight, so
    ``price`` is already per pound, while on a packaged line the quantity is a
    count and ``price`` is per package. Comparing those to each other measures
    how much was bought, not what it cost.

    RED INSTANT YEAST is the case that showed it. Five purchases of the same
    bulk yeast at $10.06-$11.00 a pound, but ``price`` reads 10.06, 1.41, 1.31,
    1.76, 2.24 — an apparent swing of 260% where the real one is 9%.

    Returns (price, basis). The basis is a normalised unit when the line has a
    weight, and "each" otherwise; callers must only compare prices that share
    a basis.
    """
    price = float(receipt_item.price or 0.0)
    weight = receipt_item.weight
    if not weight or weight <= 0:
        return price, "each"

    unit = normalise_unit(receipt_item.unit_type)
    if unit == "each":
        return price, "each"

    is_bulk = False
    if receipt_item.notes:
        try:
            is_bulk = bool(json.loads(receipt_item.notes).get("is_bulk"))
        except (json.JSONDecodeError, TypeError, AttributeError):
            is_bulk = False

    per_unit = weighted_unit_price(
        line_total(receipt_item),
        receipt_item.quantity,
        weight,
        is_weight_priced(receipt_item.quantity, weight, is_bulk),
    )
    if per_unit is None or per_unit <= 0:
        return price, "each"
    return per_unit, unit
