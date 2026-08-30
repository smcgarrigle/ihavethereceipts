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
