from app.api.analytics_fragments import _calculate_unit_price


def test_unit_price_math_multi_pack():
    """
    Scenario: Barrys Tea Bags (Pack of 6)
    - Total Line Price: $42.86
    - Quantity: 6
    - Weight: 8.8 oz
    - Stored Unit Price ($/ea): $7.1433... (42.86 / 6)

    Expected $/oz: 7.1433 / 8.8 = 0.8117
    """
    price_per_qty = 42.86 / 6
    qty = 6
    weight = 8.8
    unit = "oz"
    category = "pantry"  # Tea is pantry

    price_per_oz, label, _ = _calculate_unit_price(price_per_qty, qty, weight, unit, category)

    # Old math would do: (7.1433 * 6) / 8.8 = 4.87125
    # New math should do: 7.1433 / 8.8 = 0.8117

    print(f"DEBUG: price_per_qty={price_per_qty}, oz_price={price_per_oz}")

    assert label == "$/oz"
    # We allow some precision delta
    # If it fails, it will likely be 4.87 vs 0.81
    assert round(price_per_oz, 2) == 0.81


def test_unit_price_math_produce():
    """
    Scenario: Bag of Oranges
    - Qty: 1
    - Weight: 5 lb
    - Total/Unit Price: $10.00

    Expected $/lb: 10.00 / 5 = 2.00
    """
    price = 10.00
    qty = 1
    weight = 5.0
    unit = "lb"
    category = "produce"

    price_per_lb, label, _ = _calculate_unit_price(price, qty, weight, unit, category)

    assert label == "$/lb"
    assert round(price_per_lb, 2) == 2.00
