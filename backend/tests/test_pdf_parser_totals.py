"""Guards on money parsing in the PDF fast path.

Totals were matched with ``\\$([0-9.]+)``, a character class that excludes the
thousands separator, so ``'Grand Total: $1,024.99'`` captured ``'1'`` and a
four-figure order was stored as ``total_amount = 1.0``. Because the parser
found an order number it reported success, so the model fallback never ran and
nothing corrected it.

The same class excluded four-figure line items, which were then read as name
fragments and vanished from the item list entirely.
"""

import pytest

from app.services.pdf_parser import (
    MONEY,
    MONEY_CENTS,
    _money,
    _total_is_credible,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("4.99", 4.99),
        ("1,024.99", 1024.99),
        ("12,345.67", 12345.67),
        ("999.99", 999.99),
        ("1,000", 1000.0),
    ],
)
def test_money_strips_thousands_separators(raw, expected):
    assert _money(raw) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Grand Total: $1,024.99", "1,024.99"),
        ("Grand Total: $84.20", "84.20"),
        ("Order Total: $12,345.67", "12,345.67"),
    ],
)
def test_money_pattern_captures_the_whole_amount(text, expected):
    """The pattern must not stop at the comma."""
    import re

    m = re.search(rf"(?:Grand|Order) Total:\s+\$({MONEY})", text, re.IGNORECASE)
    assert m is not None
    assert m.group(1) == expected


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("$4.99", "4.99"),
        ("$1,024.99", "1,024.99"),
    ],
)
def test_price_only_lines_accept_four_figure_amounts(line, expected):
    """A four-figure line item used to fall through and be read as a name."""
    import re

    m = re.match(rf"^\$({MONEY_CENTS})$", line)
    assert m is not None, f"{line!r} did not match as a price line"
    assert m.group(1) == expected


def _result(total, prices):
    return {
        "total_amount": total,
        "items": [{"final_price": p} for p in prices],
    }


def test_reconciliation_rejects_the_thousands_separator_failure():
    """The exact shape of the bug: items add up, the total reads as $1.00."""
    assert _total_is_credible(_result(1.0, [412.50, 300.00, 312.49])) is False


def test_reconciliation_accepts_a_normal_receipt():
    assert _total_is_credible(_result(50.10, [20.05, 18.00, 12.05])) is True


def test_reconciliation_accepts_items_summing_below_the_total():
    """Tax or a fee that never parsed is ordinary — only the other direction is a fault."""
    assert _total_is_credible(_result(54.32, [20.05, 18.00, 12.05])) is True


def test_reconciliation_tolerates_mild_over_collection():
    """The heuristic loops can double-count; the guard must not be trigger-happy."""
    assert _total_is_credible(_result(50.00, [30.00, 25.00, 20.00])) is True


def test_reconciliation_ignores_small_absolute_differences():
    """A $2 receipt reading $0.50 is not worth a model round-trip."""
    assert _total_is_credible(_result(0.50, [2.00])) is True


def test_reconciliation_rejects_items_with_no_total_at_all():
    assert _total_is_credible(_result(0.0, [412.50, 300.00])) is False


def test_reconciliation_passes_when_there_are_no_priced_items():
    """Nothing to reconcile against — leave the result alone."""
    assert _total_is_credible(_result(0.0, [])) is True
    assert _total_is_credible(_result(25.00, [])) is True
