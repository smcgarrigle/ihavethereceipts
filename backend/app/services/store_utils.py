import re


def normalize_store_name(name: str) -> str:
    """
    Normalize store name to Title Case and handle aliases.
    This logic is shared between the API (upload) and maintenance scripts.
    """
    if not name:
        return "Unknown Store"

    name = name.strip()

    # Specific Aliases (Keys must be UPPERCASE for case-insensitive matching)
    aliases = {
        "TRADER JOES": "Trader Joe's",
        "TRADER JOE'S": "Trader Joe's",
        "COSTCO WHOLESALE": "Costco",
        "COSTCO": "Costco",
        "WFM": "Whole Foods Market",
        "WHOLE FOODS": "Whole Foods Market",
        "WHOLE FOODS MARKET": "Whole Foods Market",
        "RAINBOW GROCERY": "Rainbow Grocery",
        "RAINBOW": "Rainbow Grocery",
        "SAFEWAY": "Safeway",
        "APPETITO": "Appetito",
        "TARGET": "Target",
        "WALMART": "Walmart",
        "FRESH": "Amazon Fresh",
        "AMAZON FRESH": "Amazon Fresh",
        "AMAZON.COM": "Amazon.com",
        "AMAZON": "Amazon.com",
    }

    upper_name = name.upper()
    if upper_name in aliases:
        return aliases[upper_name]

    normalized = name.title()
    # Fix possessive 's (e.g. Farmer'S -> Farmer's)
    return re.sub(r"'S\b", "'s", normalized)
