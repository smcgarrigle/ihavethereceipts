def convert_to_grams(weight: float | None, unit_type: str | None) -> float | None:
    """
    Converts a given weight and unit to grams.
    """
    if not weight or not unit_type:
        return None

    unit = unit_type.lower().strip()

    # Direct gram equivalents
    if unit in ["g", "gram", "grams", "gr"]:
        return float(weight)

    # Ounces to grams
    if unit in ["oz", "ounce", "ounces"]:
        return float(weight) * 28.3495

    # Pounds to grams
    if unit in ["lb", "lbs", "pound", "pounds"]:
        return float(weight) * 453.592

    # ML to grams (1:1 approximation for water-based foods)
    if unit in ["ml", "milliliter", "milliliters", "ml."]:
        return float(weight)

    # Fluid Ounces to grams (approximation)
    if unit in ["fl oz", "fluid ounce", "floz"]:
        return float(weight) * 29.5735

    # Kilograms to grams
    if unit in ["kg", "kilogram", "kilograms"]:
        return float(weight) * 1000.0

    # Liters to grams (1:1000 approximation)
    if unit in ["l", "liter", "liters"]:
        return float(weight) * 1000.0

    return None


def resolve_purchase_grams(receipt_item, item_name: str | None = None) -> float | None:
    """
    Best-effort total grams for a purchase line.

    1. Explicit weight on the receipt line (bulk/per-lb items).
    2. Package-size fallback: a size embedded in the item name (e.g. "16OZ",
       "5LB") × quantity — covers discrete items (jars, boxes, packs) that
       previously contributed nothing to nutrition analytics.
    """
    grams = convert_to_grams(receipt_item.weight, receipt_item.unit_type)
    if grams:
        return grams

    from app.utils.item_parsing import extract_weight

    name = item_name or (receipt_item.item.name if receipt_item.item else None)
    if not name:
        return None

    pkg_value, pkg_unit = extract_weight(name)
    pkg_grams = convert_to_grams(pkg_value, pkg_unit)
    if not pkg_grams:
        return None

    quantity = receipt_item.quantity or 1
    return pkg_grams * quantity


def calculate_receipt_item_macros(receipt_item) -> dict[str, float] | None:
    """
    Given a ReceiptItem (which has a relationship to an Item with nutrients),
    calculates the absolute macros yielded by this specific purchase.
    """
    item = receipt_item.item
    if not item:
        return None

    # Manual overrides (custom_nutrients) take precedence over canonical data
    nutrients = item.effective_nutrients
    if not nutrients:
        return None

    # Attempt to get the total weight in grams
    grams = resolve_purchase_grams(receipt_item)
    if not grams:
        # Fallback: if we can't figure out the weight, we can't calculate absolute macros
        return None

    multiplier = grams / 100.0
    return {
        "protein_g": round(float(nutrients.get("proteins_100g", 0)) * multiplier, 2),
        "carbs_g": round(float(nutrients.get("carbohydrates_100g", 0)) * multiplier, 2),
        "fat_g": round(float(nutrients.get("fat_100g", 0)) * multiplier, 2),
        "energy_kcal": round(float(nutrients.get("energy-kcal_100g", 0)) * multiplier, 2),
        "total_weight_g": round(grams, 2),
    }


def determine_macro_dominant(macros: dict[str, float]) -> str:
    """
    Determines if a food is protein-dominant, carb-dominant, fat-dominant, mixed, or other.
    Based on caloric contribution.
    Protein/Carb = 4 kcal/g, Fat = 9 kcal/g.
    """
    p_cals = macros.get("protein_g", 0) * 4
    c_cals = macros.get("carbs_g", 0) * 4
    f_cals = macros.get("fat_g", 0) * 9

    total_cals = p_cals + c_cals + f_cals
    if total_cals == 0:
        return "Non-nutritive / Other"

    p_pct = p_cals / total_cals
    c_pct = c_cals / total_cals
    f_pct = f_cals / total_cals

    if p_pct >= 0.40:
        return "Protein-dominant"
    elif c_pct >= 0.40:
        return "Carb-dominant"
    elif f_pct >= 0.40:
        return "Fat-dominant"
    else:
        return "Mixed macro"
