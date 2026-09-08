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

from typing import Any

from app.models import ReceiptItem

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
