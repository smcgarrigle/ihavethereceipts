"""Audit finding 08: the backfill must not write a per-weight figure into price.

ReceiptItem.price is the per-quantity price the whole app multiplies by quantity
(app/services/spend.py). unit_price is the per-pound figure for bulk lines.
Collapsing the two turned a $3.99 five-pound bag of potatoes into eighty cents of
recorded spend, and the script is documented in CHEATSHEET.md as routine
maintenance.
"""

from __future__ import annotations

import datetime
import importlib.util
import json
from pathlib import Path

import pytest
from conftest import TestingSessionLocal

from app.models import Item, Receipt, ReceiptItem, Store
from app.services.spend import line_total

BACKFILL = Path(__file__).resolve().parent.parent / "scripts" / "backfill_unit_prices.py"


@pytest.fixture
def backfill_module():
    """Load the script and point it at the test database."""
    spec = importlib.util.spec_from_file_location("backfill_unit_prices", BACKFILL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.SessionLocal = TestingSessionLocal
    return module


def _line(db, name, *, quantity, price, weight, unit_type, base_price, is_bulk):
    store = db.query(Store).filter(Store.name == "Backfill Test Store").first()
    if not store:
        store = Store(name="Backfill Test Store")
        db.add(store)
        db.commit()
        db.refresh(store)

    receipt = Receipt(
        store_id=store.id,
        total_amount=base_price,
        purchase_date=datetime.datetime.now(),
        status="completed",
    )
    item = Item(name=name, normalized_name=name.lower())
    db.add_all([receipt, item])
    db.commit()
    db.refresh(receipt)
    db.refresh(item)

    line = ReceiptItem(
        receipt_id=receipt.id,
        item_id=item.id,
        quantity=quantity,
        price=price,
        unit_price=None,
        weight=weight,
        unit_type=unit_type,
        notes=json.dumps({"base_price": base_price, "discounts": [], "is_bulk": is_bulk}),
    )
    db.add(line)
    db.commit()
    db.refresh(line)
    return line.id


def test_bulk_line_keeps_its_per_unit_price(db, backfill_module):
    """A 5lb bag of potatoes at $3.99 is $3.99 of spend, not $0.80."""
    line_id = _line(
        db,
        "RUSSET POT 5LB",
        quantity=1,
        price=3.99,
        weight=5.0,
        unit_type="lb",
        base_price=3.99,
        is_bulk=True,
    )
    db.commit()
    db.close()

    backfill_module.backfill(dry_run=False)

    line = db.query(ReceiptItem).filter(ReceiptItem.id == line_id).one()
    assert line.price == pytest.approx(3.99), "the per-pound figure was written to price"
    assert line.unit_price == pytest.approx(0.798), "unit_price should carry dollars per pound"
    assert line_total(line) == pytest.approx(3.99)


def test_bulk_line_with_quantity_divides_out_both(db, backfill_module):
    """Two 5lb bags at $7.98 total: $3.99 each, $0.798 per pound."""
    line_id = _line(
        db,
        "RUSSET POT 5LB",
        quantity=2,
        price=0.0,
        weight=5.0,
        unit_type="lb",
        base_price=7.98,
        is_bulk=True,
    )
    db.commit()
    db.close()

    backfill_module.backfill(dry_run=False)

    line = db.query(ReceiptItem).filter(ReceiptItem.id == line_id).one()
    assert line.price == pytest.approx(3.99)
    assert line.unit_price == pytest.approx(0.798)
    assert line_total(line) == pytest.approx(7.98)


def test_packaged_line_is_unchanged_in_meaning(db, backfill_module):
    """Non-bulk lines: both columns are the per-quantity price."""
    line_id = _line(
        db,
        "CANNED BEANS",
        quantity=3,
        price=0.0,
        weight=None,
        unit_type=None,
        base_price=3.87,
        is_bulk=False,
    )
    db.commit()
    db.close()

    backfill_module.backfill(dry_run=False)

    line = db.query(ReceiptItem).filter(ReceiptItem.id == line_id).one()
    assert line.price == pytest.approx(1.29)
    assert line.unit_price == pytest.approx(1.29)
    assert line_total(line) == pytest.approx(3.87)


def test_dry_run_writes_nothing(db, backfill_module):
    line_id = _line(
        db,
        "RUSSET POT 5LB",
        quantity=1,
        price=3.99,
        weight=5.0,
        unit_type="lb",
        base_price=3.99,
        is_bulk=True,
    )
    db.commit()
    db.close()

    backfill_module.backfill(dry_run=True)

    line = db.query(ReceiptItem).filter(ReceiptItem.id == line_id).one()
    assert line.price == pytest.approx(3.99)
    assert line.unit_price is None
