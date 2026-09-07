import re


def extract_weight(name: str) -> tuple[float | None, str | None]:
    """
    Extracts weight/volume and unit from a string.
    Returns (value, unit) or (None, None).
    """
    if not name:
        return None, None

    # Common patterns: "32 Ounce", "16OZ", "5LB", "0.8 oz", "40 oz (1.13 kg)"
    # Handling fl oz specifically
    pattern_fl_oz = r"(\d+(?:\.\d+)?)\s*(fl\s*oz|FL\s*OZ|Fl\s*Oz)\b"
    match = re.search(pattern_fl_oz, name, re.IGNORECASE)
    if match:
        return float(match.group(1)), "fl oz"

    # General pattern for other units
    pattern_general = r"(\d+(?:\.\d+)?)\s*(oz|lb|lbs|ounce|g|gram|kg|l|ml|cl|pt|qt|gal)\b"
    match = re.search(pattern_general, name, re.IGNORECASE)
    if match:
        val = float(match.group(1))
        unit = match.group(2).lower()
        # Normalize unit names
        if unit in ["ounce", "oz"]:
            unit = "oz"
        if unit in ["lb", "lbs"]:
            unit = "lb"
        # Basic normalization for common units
        if unit in ["gram", "g"]:
            unit = "g"
        return val, unit

    return None, None


def weighted_unit_price(
    line_total: float,
    quantity: float | None,
    weight: float | None,
    is_bulk: bool = False,
) -> float | None:
    """Price of ONE unit of ``unit_type`` for a line, or None if there is no weight.

    This is the meaning the ``unit_price`` column is read with: ``items.py``
    normalises it straight to $/oz (``up / 16.0`` when unit_type is "lb"), so a
    per-package figure stored there is overstated by the package size.

    The divisor depends on what ``weight`` counts, which is what ``is_bulk``
    distinguishes:

    * weight-priced line ("@ $2.49/lb") -- ``weight`` is the total weight
      bought, so the line total is already spread across it.
    * packaged line ("BEANS 15OZ" x3) -- ``weight`` is the size of ONE package,
      so the total has to be divided by both the number of packages and that
      size: 3 x 15 oz at $3.87 is $0.086/oz, not $0.258.

    ``quantity == weight`` is treated as weight-priced whatever ``is_bulk``
    says, because the model does not always set the flag on a loose-produce
    line. Measured over the 1,682 weighted lines in the live database: all 98
    such rows are loose weight-priced produce and deli ("OG SWT POTATO", qty
    2.51, weight 2.51 lb), and the only integer case is qty == weight == 1,
    where both formulas give the same answer.
    """
    if not weight or weight <= 0:
        return None
    qty = quantity if quantity and quantity > 0 else 1.0
    if is_bulk or abs(qty - weight) < 1e-6:
        return round(line_total / weight, 4)
    return round(line_total / (qty * weight), 4)
