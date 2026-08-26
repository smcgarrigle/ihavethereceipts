"""The demo seed must produce receipts whose line items add up to the receipt total.

ReceiptItem.price is a per-quantity price throughout the app — spend is read as
price * quantity (analytics.py, receipts.py, receipts_review.py). Seeding the line
total there instead double-counted every qty>1 line, which inflated all spend
figures and made the review page's total-mismatch warning fire on most receipts.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from conftest import TestingSessionLocal

from app.models import Receipt, ReceiptItem

SEED_DEMO = Path(__file__).resolve().parent.parent / "scripts" / "seed_demo.py"


@pytest.fixture
def seeded(db):
    """Seed the throwaway test database and hand back a session over it."""
    spec = importlib.util.spec_from_file_location("seed_demo_under_test", SEED_DEMO)
    seed_demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed_demo)
    # seed() resolves SessionLocal as a module global, so patching the attribute
    # redirects it onto the in-memory test engine.
    seed_demo.SessionLocal = TestingSessionLocal
    seed_demo.seed()
    return db


def test_line_items_sum_to_receipt_total(seeded):
    """price * quantity must reconstruct each receipt's stored total."""
    receipts = seeded.query(Receipt).filter(Receipt.notes == "DEMO_DATA").all()
    assert receipts, "seed produced no demo receipts"

    mismatched = []
    for receipt in receipts:
        line_sum = sum(ri.price * ri.quantity for ri in receipt.items)
        # A cent per line is possible from rounding price to 2dp; anything beyond
        # that is a real accounting error, not float noise.
        tolerance = max(0.02, 0.01 * len(receipt.items))
        if abs(line_sum - (receipt.total_amount or 0.0)) > tolerance:
            mismatched.append((receipt.id, round(line_sum, 2), receipt.total_amount))

    assert not mismatched, (
        f"{len(mismatched)} of {len(receipts)} demo receipts have line items that do "
        f"not sum to their total (id, line_sum, total): {mismatched[:5]}"
    )


def test_multi_quantity_lines_are_not_double_counted(seeded):
    """The specific regression: a qty>1 line storing its line total as the price."""
    multi = seeded.query(ReceiptItem).filter(ReceiptItem.quantity > 1).all()
    assert multi, "seed produced no qty>1 lines, so this guard proves nothing"

    # unit_price is stored separately and is the true per-unit figure, so it is an
    # independent yardstick: with the bug, price came out as unit_price * quantity.
    wrong = [
        (ri.id, ri.quantity, ri.price, ri.unit_price)
        for ri in multi
        if ri.unit_price and abs(ri.price - ri.unit_price) > 0.02
    ]
    assert not wrong, (
        f"{len(wrong)} of {len(multi)} qty>1 lines store a price that is not the "
        f"per-unit price (id, qty, price, unit_price): {wrong[:5]}"
    )
