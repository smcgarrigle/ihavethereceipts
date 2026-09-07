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


def test_packaged_line_with_weight_gets_a_per_ounce_unit_price(db, backfill_module):
    """The repair this script now has to be able to do.

    984 of the 1,584 packaged lines in the live database hold a per-package
    figure in unit_price, which items.py reads as $/oz. Gating the per-weight
    computation on is_bulk left them there — and rewrote the 551 correct ones
    to match.
    """
    line_id = _line(
        db,
        "WHEAT GERM 12 OZ",
        quantity=2,
        price=3.1,
        weight=12.0,
        unit_type="oz",
        base_price=6.2,
        is_bulk=False,
    )
    db.commit()
    db.close()

    backfill_module.backfill(dry_run=False)

    line = db.query(ReceiptItem).filter(ReceiptItem.id == line_id).one()
    assert line.price == pytest.approx(3.1), "price stays the per-quantity price"
    assert line.unit_price == pytest.approx(0.2583), "unit_price is dollars per ounce"
    assert line_total(line) == pytest.approx(6.2)


def test_weight_priced_line_is_not_divided_twice(db, backfill_module):
    """10.756 gal of fuel at $57.01 is $5.30/gal, not $0.49.

    On a weight-priced line the quantity IS the weight bought, so the line
    total is already spread across it.
    """
    line_id = _line(
        db,
        "Regular Gasoline",
        quantity=10.756,
        price=5.2994,
        weight=10.756,
        unit_type="gal",
        base_price=57.01,
        is_bulk=True,
    )
    db.commit()
    db.close()

    backfill_module.backfill(dry_run=False)

    line = db.query(ReceiptItem).filter(ReceiptItem.id == line_id).one()
    assert line.unit_price == pytest.approx(5.3003, abs=1e-3)
    assert line_total(line) == pytest.approx(57.01, abs=0.01)


def test_weight_found_in_the_name_reaches_unit_price_in_the_same_pass(db, backfill_module):
    """Weight extraction used to run after the price recompute.

    A row whose weight is discovered here would keep a per-package unit_price
    until the script was run a second time — the same ordering mistake the
    review endpoint had.
    """
    line_id = _line(
        db,
        "MARYS CRACKERS 5.5OZ",
        quantity=2,
        price=4.075,
        weight=None,
        unit_type=None,
        base_price=8.15,
        is_bulk=False,
    )
    db.commit()
    db.close()

    backfill_module.backfill(dry_run=False)

    line = db.query(ReceiptItem).filter(ReceiptItem.id == line_id).one()
    assert line.weight == pytest.approx(5.5)
    assert line.unit_type == "oz"
    assert line.unit_price == pytest.approx(0.7409), "8.15 / (2 * 5.5)"


def test_dry_run_reports_the_number_a_real_run_would_write(db, backfill_module, capsys):
    """--dry-run is the whole safety story, so it must not under-report."""
    _line(
        db,
        "MARYS CRACKERS 5.5OZ",
        quantity=2,
        price=4.075,
        weight=None,
        unit_type=None,
        base_price=8.15,
        is_bulk=False,
    )
    db.commit()
    db.close()

    backfill_module.backfill(dry_run=True)

    out = capsys.readouterr().out
    assert "0.7409" in out, f"dry run reported a per-package figure instead:\n{out}"


def test_name_derived_weight_matching_quantity_is_still_a_package(db, backfill_module):
    """Four 4 oz jars of peppercorns, not 4 oz bought loose.

    The script recovers weights from names for 241 rows in the live database.
    None of them currently collides with its quantity, but the quantity ==
    weight test must not apply to them regardless: it would price this line at
    $28.08/oz instead of $7.02.
    """
    line_id = _line(
        db,
        "Tellicherry Peppercorns 4 oz",
        quantity=4,
        price=28.08,
        weight=None,
        unit_type=None,
        base_price=112.32,
        is_bulk=False,
    )
    db.commit()
    db.close()

    backfill_module.backfill(dry_run=False)

    line = db.query(ReceiptItem).filter(ReceiptItem.id == line_id).one()
    assert line.weight == pytest.approx(4.0)
    assert line.unit_price == pytest.approx(7.02), "112.32 / (4 * 4)"
    assert line_total(line) == pytest.approx(112.32)


def test_weight_priced_line_with_a_squared_divisor_is_repaired(db, backfill_module):
    """$1.37 of bananas over 1.54 lb is $0.89/lb, stored as 1.37 / 1.54².

    On these lines quantity IS the weight, so dividing by both squares the
    divisor. All 50 such rows in the live database carry that signature.
    """
    line_id = _line(
        db,
        "BANANA",
        quantity=1.54,
        price=0.8896,
        weight=1.54,
        unit_type="lb",
        base_price=1.37,
        is_bulk=True,
    )
    line = db.query(ReceiptItem).filter(ReceiptItem.id == line_id).one()
    line.unit_price = round(1.37 / (1.54 * 1.54), 2)  # 0.58, what the bug wrote
    db.commit()
    db.close()

    backfill_module.backfill(dry_run=False)

    line = db.query(ReceiptItem).filter(ReceiptItem.id == line_id).one()
    assert line.unit_price == pytest.approx(0.8896, abs=1e-3)


def test_a_genuinely_disagreeing_price_is_reported_not_overwritten(db, backfill_module, capsys):
    """Anything that is not the bug's signature is left for a human to judge."""
    line_id = _line(
        db,
        "OG SWT POTATO",
        quantity=2.51,
        price=1.988,
        weight=2.51,
        unit_type="lb",
        base_price=4.99,
        is_bulk=True,
    )
    line = db.query(ReceiptItem).filter(ReceiptItem.id == line_id).one()
    line.unit_price = 1.5  # neither the derived 1.988 nor the squared 0.79
    db.commit()
    db.close()

    backfill_module.backfill(dry_run=False)

    line = db.query(ReceiptItem).filter(ReceiptItem.id == line_id).one()
    assert line.unit_price == pytest.approx(1.5), "a disputed price was overwritten"
    out = capsys.readouterr().out
    assert "disagrees with their own total" in out
    assert "OG SWT POTATO" in out


def test_missing_unit_price_on_a_weight_priced_line_is_filled_in(db, backfill_module):
    """Leaving a stated price alone is not the same as never writing one."""
    line_id = _line(
        db,
        "OG VINE TOMATO",
        quantity=0.74,
        price=3.9865,
        weight=0.74,
        unit_type="lb",
        base_price=2.95,
        is_bulk=True,
    )
    db.commit()
    db.close()

    backfill_module.backfill(dry_run=False)

    line = db.query(ReceiptItem).filter(ReceiptItem.id == line_id).one()
    assert line.unit_price == pytest.approx(3.9865, abs=1e-3)
