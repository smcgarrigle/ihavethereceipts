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


def is_weight_priced(
    quantity: float | None,
    weight: float | None,
    is_bulk: bool = False,
) -> bool:
    """Whether ``weight`` is the total weight bought rather than a package size.

    Only ever ask this of a weight that came off the receipt line or the model.
    A size parsed out of an item NAME is a package label by construction, so
    the caller passes ``weight_priced=False`` for those without consulting this.

    ``quantity == weight`` counts as weight-priced whatever ``is_bulk`` says,
    because the model does not reliably set the flag on a loose-produce line
    ("CUCUMBER PERSIAN", quantity 0.88, weight 0.88 lb, flag unset). Measured
    over the 1,682 stored weighted lines in the live database: all 98 such rows
    are loose produce or deli, and the only integer case is qty == weight == 1,
    where both readings give the same answer.
    """
    if is_bulk:
        return True
    if not weight or not quantity or weight <= 0 or quantity <= 0:
        return False
    return abs(quantity - weight) < 1e-6


def weighted_unit_price(
    line_total: float,
    quantity: float | None,
    weight: float | None,
    weight_priced: bool = False,
) -> float | None:
    """Price of ONE unit of ``unit_type`` for a line, or None if there is no weight.

    This is the meaning the ``unit_price`` column is read with: ``items.py``
    normalises it straight to $/oz (``up / 16.0`` when unit_type is "lb"), so a
    per-package figure stored there is overstated by the package size.

    The divisor depends on what ``weight`` counts, and the caller decides that
    -- typically with :func:`is_weight_priced`, except where the weight was
    parsed out of an item name and is therefore a package size:

    * ``weight_priced`` -- ``weight`` is the total weight bought ("@ $2.49/lb"),
      so the line total is already spread across it.
    * otherwise -- ``weight`` is the size of ONE package, so the total has to be
      divided by both the number of packages and that size: 3 x 15 oz at $3.87
      is $0.086/oz, not $0.258.

    The two are kept apart structurally rather than on measured evidence: no
    row in the current corpus has a name-derived weight equal to its quantity.
    But nothing stops one -- four 12 oz jars would do it -- and a size printed
    in a name is never a total weight bought, so the caller says so outright
    instead of letting the arithmetic decide.
    """
    if not weight or weight <= 0:
        return None
    qty = quantity if quantity and quantity > 0 else 1.0
    if weight_priced:
        return round(line_total / weight, 4)
    return round(line_total / (qty * weight), 4)


# Spellings of the same unit that reach us from OCR and from the review form.
# "Regular Gasoline" alone arrives as gal, gallon and gallons — one purchase
# each — which is enough to leave it with no comparable series at all.
UNIT_ALIASES = {
    "gallon": "gal",
    "gallons": "gal",
    "lbs": "lb",
    "pound": "lb",
    "pounds": "lb",
    "ounce": "oz",
    "ounces": "oz",
    "fl_oz": "fl oz",
    "floz": "fl oz",
    "litre": "l",
    "liter": "l",
    "litres": "l",
    "liters": "l",
    "ea": "each",
    "": "each",
}


def normalise_unit(unit: str | None) -> str:
    """One spelling per unit, so two purchases of the same thing can be compared."""
    if not unit:
        return "each"
    cleaned = unit.strip().lower()
    return UNIT_ALIASES.get(cleaned, cleaned)
