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
