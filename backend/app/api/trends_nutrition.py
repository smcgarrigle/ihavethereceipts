"""Nutrition trends — coverage stats, macro profiles, and nutrient chart data.

Split from trends.py; spend/category trend endpoints remain there. Both
routers are mounted under /api/trends.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Item, Receipt, ReceiptItem

router = APIRouter()

# Outlier winsorization for nutrition charts. 0 disables capping.
ALLOWED_PERCENTILES = {0, 80, 85, 90, 95}
DEFAULT_PERCENTILE = 95
# Below this many positive data points per nutrient, the percentile is too
# noisy to be a meaningful cap, so capping is skipped for that nutrient.
MIN_WINSORIZE_POINTS = 8
_NUTRIENT_KEYS = ("fat", "saturated_fat", "sugar", "protein", "sodium")


@router.get("/usda-product-types")
def get_usda_product_types(time_range: str = "all", db: Session = Depends(get_db)):
    """
    Get pie chart data for USDA product types by purchase count.
    """
    from datetime import datetime, timedelta

    from sqlalchemy import func

    from app.models import Category, Item, Receipt, ReceiptItem

    end_date = datetime.now()
    if time_range == "year":
        start_date = end_date - timedelta(days=365)
    elif time_range == "6m":
        start_date = end_date - timedelta(days=180)
    elif time_range == "3m":
        start_date = end_date - timedelta(days=90)
    else:
        start_date = None

    query = (
        db.query(Category.name, func.count(ReceiptItem.id).label("purchase_count"))
        .join(Item, ReceiptItem.item_id == Item.id)
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .join(Category, Item.category_id == Category.id)
        .filter(Item.fdc_id.isnot(None))
    )

    if start_date:
        query = query.filter(Receipt.purchase_date >= start_date)

    results = query.group_by(Category.name).order_by(func.count(ReceiptItem.id).desc()).all()

    if not results:
        return {"labels": [], "datasets": []}

    labels = []
    data = []
    other_count = 0

    for i, row in enumerate(results):
        if i < 10:
            labels.append(row.name)
            data.append(row.purchase_count)
        else:
            other_count += row.purchase_count

    if other_count > 0:
        labels.append("Other")
        data.append(other_count)

    colors = [
        "#3b82f6",
        "#10b981",
        "#f59e0b",
        "#ef4444",
        "#8b5cf6",
        "#ec4899",
        "#14b8a6",
        "#f97316",
        "#6366f1",
        "#84cc16",
        "#64748b",
    ]

    return {
        "labels": labels,
        "datasets": [
            {
                "data": data,
                "backgroundColor": colors[: len(labels)],
                "borderWidth": 0,
                "hoverOffset": 4,
            }
        ],
    }


def _json_present(col):
    """True when a JSON column holds real data — excludes SQL NULL and JSON null
    (SQLAlchemy stores an explicitly-assigned Python None as JSON 'null' text)."""
    from sqlalchemy import String, and_, cast

    return and_(col.is_not(None), cast(col, String) != "null")


def _get_raw_nutrition_data(time_range: str, db: Session):
    import json
    from datetime import datetime, timedelta

    now = datetime.now()
    if time_range == "3m":
        start_date = now - timedelta(days=90)
    elif time_range == "6m":
        start_date = now - timedelta(days=180)
    elif time_range == "ytd":
        start_date = datetime(now.year, 1, 1)
    elif time_range == "year":
        start_date = now - timedelta(days=365)
    else:
        start_date = None

    query = (
        db.query(
            func.strftime("%Y-%W", Receipt.purchase_date).label("week"),
            Item.name,
            Item.nutrients,
            Item.custom_nutrients,
            ReceiptItem.weight,
            ReceiptItem.unit_type,
            ReceiptItem.quantity,
        )
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .join(Item, ReceiptItem.item_id == Item.id)
        .filter(or_(_json_present(Item.nutrients), _json_present(Item.custom_nutrients)))
    )

    if start_date and time_range != "all":
        query = query.filter(Receipt.purchase_date >= start_date)

    results = query.all()

    conv = {"lb": 453.592, "oz": 28.3495, "g": 1.0, "kg": 1000.0}

    def safe_float(v):
        try:
            return float(v) if v is not None else 0.0
        except (ValueError, TypeError):
            return 0.0

    def merge_nutrients(base, custom):
        base = base if not isinstance(base, str) else json.loads(base)
        custom = custom if not isinstance(custom, str) else json.loads(custom)
        merged = dict(base or {})
        for k, v in (custom or {}).items():
            if v is not None and str(v).strip() != "":
                merged[k] = v
        return merged

    from app.utils.item_parsing import extract_weight

    parsed_records = []
    for row in results:
        if not row.week:
            continue

        nutrients = merge_nutrients(row.nutrients, row.custom_nutrients)
        if not nutrients:
            continue

        weight = row.weight or 0
        unit = (row.unit_type or "oz").lower().strip()
        qty = row.quantity or 1
        weight_g = weight * conv.get(unit, 28.35) * qty

        if weight_g == 0 and row.name:
            # Package-size fallback for discrete items: parse a size embedded in
            # the item name (e.g. "16OZ", "5LB") and scale by quantity
            pkg_value, pkg_unit = extract_weight(row.name)
            if pkg_value and pkg_unit in conv:
                weight_g = pkg_value * conv[pkg_unit] * qty

        if weight_g == 0:
            continue

        fat_g = safe_float(nutrients.get("fat_100g", 0)) * (weight_g / 100.0)
        saturated_fat_g = safe_float(nutrients.get("saturated-fat_100g", 0)) * (weight_g / 100.0)
        sugar_g = safe_float(nutrients.get("sugars_100g", 0)) * (weight_g / 100.0)
        protein_g = safe_float(nutrients.get("proteins_100g", 0)) * (weight_g / 100.0)
        sodium_mg = safe_float(nutrients.get("sodium_100g", 0)) * (weight_g / 100.0) * 1000.0

        parsed_records.append(
            {
                "week": row.week,
                "item_name": row.name or "Unknown Item",
                "fat": fat_g,
                "saturated_fat": saturated_fat_g,
                "sugar": sugar_g,
                "protein": protein_g,
                "sodium": sodium_mg,
            }
        )

    return parsed_records


def _get_outlier_percentile() -> int:
    from app.api.settings_router import _load_feature_flags

    raw = _load_feature_flags().get("nutrition_outlier_percentile", DEFAULT_PERCENTILE)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PERCENTILE
    return value if value in ALLOWED_PERCENTILES else DEFAULT_PERCENTILE


def _winsorize_rows(rows: list[dict], percentile: int) -> tuple[list[dict], dict]:
    """Cap per-purchase nutrient values above the Nth percentile.

    Each nutrient is capped independently against its own distribution of
    positive values within the rows; zeros mean "nutrient absent" and would
    collapse the cap if included. The cap is a floor-rank order statistic
    clamped to at most the second-largest value: with ceil (true nearest-rank)
    the p95 of fewer than 20 points is the max itself, which would leave a
    lone salt-bomb purchase uncapped on sparse data. Values equal to the cap
    are never modified. Mutates rows in place.
    """
    import math

    meta: dict = {
        "enabled": bool(percentile),
        "percentile": percentile,
        "capped_points": 0,
        "per_nutrient": {},
    }
    if not percentile or not rows:
        return rows, meta

    for key in _NUTRIENT_KEYS:
        vals = sorted(r[key] for r in rows if r[key] > 0)
        if len(vals) < MIN_WINSORIZE_POINTS:
            continue
        rank = max(1, min(math.floor(percentile / 100.0 * len(vals)), len(vals) - 1))
        cap = vals[rank - 1]
        capped = 0
        for r in rows:
            if r[key] > cap:
                r[key] = cap
                capped += 1
        if capped:
            meta["per_nutrient"][key] = {"cap": round(cap, 1), "capped": capped}
            meta["capped_points"] += capped

    return rows, meta


def _get_nutrition_data(time_range: str, db: Session) -> tuple[list[dict], dict]:
    """Raw nutrition rows with the user's outlier capping applied."""
    return _winsorize_rows(_get_raw_nutrition_data(time_range, db), _get_outlier_percentile())


def get_nutrition_coverage(time_range: str, db: Session) -> dict:
    """
    How much of the purchase data actually backs the nutrition charts:
    share of spend (and of distinct items) with nutrient data in the range.
    """
    from datetime import datetime, timedelta

    now = datetime.now()
    if time_range == "3m":
        start_date = now - timedelta(days=90)
    elif time_range == "6m":
        start_date = now - timedelta(days=180)
    elif time_range == "ytd":
        start_date = datetime(now.year, 1, 1)
    elif time_range == "year":
        start_date = now - timedelta(days=365)
    else:
        start_date = None

    has_nutrients = or_(_json_present(Item.nutrients), _json_present(Item.custom_nutrients))

    query = (
        db.query(
            func.coalesce(func.sum(ReceiptItem.price), 0.0).label("total_spend"),
            func.coalesce(func.sum(case((has_nutrients, ReceiptItem.price), else_=0.0)), 0.0).label(
                "covered_spend"
            ),
            func.count(func.distinct(ReceiptItem.item_id)).label("total_items"),
            func.count(func.distinct(case((has_nutrients, ReceiptItem.item_id)))).label(
                "covered_items"
            ),
        )
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .join(Item, ReceiptItem.item_id == Item.id)
    )
    if start_date and time_range != "all":
        query = query.filter(Receipt.purchase_date >= start_date)

    row = query.one()
    total_spend = float(row.total_spend or 0)
    covered_spend = float(row.covered_spend or 0)
    return {
        "spend_pct": round(covered_spend / total_spend * 100, 1) if total_spend else 0.0,
        "covered_spend": round(covered_spend, 2),
        "total_spend": round(total_spend, 2),
        "covered_items": row.covered_items or 0,
        "total_items": row.total_items or 0,
    }


def get_macronutrient_calories_data(time_range: str, db: Session):
    """
    Returns weekly macronutrient caloric intake (Fat, Sugar, Protein) stacked.
    """
    results, _ = _get_nutrition_data(time_range, db)
    from collections import defaultdict

    weekly_calories: defaultdict[str, dict[str, float]] = defaultdict(
        lambda: {"fat": 0.0, "sugar": 0.0, "protein": 0.0}
    )
    all_weeks = set()

    for r in results:
        week = r["week"]
        all_weeks.add(week)
        # Fat = 9 kcal/g, Sugar = 4 kcal/g, Protein = 4 kcal/g
        weekly_calories[week]["fat"] += r["fat"] * 9.0
        weekly_calories[week]["sugar"] += r["sugar"] * 4.0
        weekly_calories[week]["protein"] += r["protein"] * 4.0

    sorted_weeks = sorted(all_weeks)

    fat_data = []
    sugar_data = []
    protein_data = []

    for w in sorted_weeks:
        fat_data.append(round(weekly_calories[w]["fat"], 1))
        sugar_data.append(round(weekly_calories[w]["sugar"], 1))
        protein_data.append(round(weekly_calories[w]["protein"], 1))

    datasets = [
        {
            "label": "Fat Calories",
            "data": fat_data,
            "backgroundColor": "#f59e0b",  # Amber
            "stack": "stack0",
        },
        {
            "label": "Sugar Calories",
            "data": sugar_data,
            "backgroundColor": "#3b82f6",  # Blue
            "stack": "stack0",
        },
        {
            "label": "Protein Calories",
            "data": protein_data,
            "backgroundColor": "#10b981",  # Emerald
            "stack": "stack0",
        },
    ]
    return {"labels": sorted_weeks, "datasets": datasets}


def get_nutrition_multiples_data(time_range: str, db: Session):
    """
    Returns weekly trend lines for Sodium, Fat, Sugar, and Protein.
    Used for Tufte small multiples.
    """
    results, _ = _get_nutrition_data(time_range, db)
    from collections import defaultdict

    weekly_totals: defaultdict[str, dict[str, float]] = defaultdict(
        lambda: {"fat": 0.0, "sugar": 0.0, "protein": 0.0, "sodium": 0.0}
    )
    all_weeks = set()

    for r in results:
        week = r["week"]
        all_weeks.add(week)
        weekly_totals[week]["fat"] += r["fat"]
        weekly_totals[week]["sugar"] += r["sugar"]
        weekly_totals[week]["protein"] += r["protein"]
        weekly_totals[week]["sodium"] += r["sodium"]

    sorted_weeks = sorted(all_weeks)

    fat_data = []
    sugar_data = []
    protein_data = []
    sodium_data = []

    for w in sorted_weeks:
        fat_data.append(round(weekly_totals[w]["fat"], 1))
        sugar_data.append(round(weekly_totals[w]["sugar"], 1))
        protein_data.append(round(weekly_totals[w]["protein"], 1))
        sodium_data.append(round(weekly_totals[w]["sodium"], 1))

    return {
        "labels": sorted_weeks,
        "sodium": sodium_data,
        "fat": fat_data,
        "sugar": sugar_data,
        "protein": protein_data,
    }


def get_nutrition_density_data(time_range: str, db: Session):
    """
    Returns average daily purchased amounts vs Daily Reference Values,
    and overall caloric ratios.
    """
    results, _ = _get_nutrition_data(time_range, db)

    from datetime import datetime

    from app.models import Receipt

    now = datetime.now()
    if time_range == "3m":
        days = 90
    elif time_range == "6m":
        days = 180
    elif time_range == "ytd":
        jan_1st = datetime(now.year, 1, 1)
        days = max(1, (now - jan_1st).days)
    elif time_range == "year":
        days = 365
    else:  # "all"
        min_date_row = (
            db.query(func.min(Receipt.purchase_date))
            .filter(Receipt.purchase_date.isnot(None))
            .first()
        )
        if min_date_row and min_date_row[0]:
            try:
                min_date = min_date_row[0]
                if isinstance(min_date, str):
                    clean_date = min_date.replace("T", " ").split(" ")[0]
                    min_dt = datetime.strptime(clean_date, "%Y-%m-%d")
                else:
                    min_dt = min_date
                days = max(1, (now - min_dt).days)
            except Exception:
                days = 180
        else:
            days = 180

    total_fat = 0.0
    total_sugar = 0.0
    total_protein = 0.0
    total_sodium = 0.0

    for r in results:
        total_fat += r["fat"]
        total_sugar += r["sugar"]
        total_protein += r["protein"]
        total_sodium += r["sodium"]

    avg_fat = total_fat / days
    avg_sugar = total_sugar / days
    avg_protein = total_protein / days
    avg_sodium = total_sodium / days

    fat_cal = total_fat * 9.0
    sugar_cal = total_sugar * 4.0
    protein_cal = total_protein * 4.0
    total_cal = fat_cal + sugar_cal + protein_cal

    if total_cal > 0:
        pct_fat = round((fat_cal / total_cal) * 100.0, 1)
        pct_sugar = round((sugar_cal / total_cal) * 100.0, 1)
        pct_protein = round((protein_cal / total_cal) * 100.0, 1)
    else:
        pct_fat = 0.0
        pct_sugar = 0.0
        pct_protein = 0.0

    references = {"fat": 78.0, "sugar": 50.0, "protein": 50.0, "sodium": 2300.0}

    return {
        "days": days,
        "averages": {
            "fat": round(avg_fat, 1),
            "sugar": round(avg_sugar, 1),
            "protein": round(avg_protein, 1),
            "sodium": round(avg_sodium, 1),
        },
        "references": references,
        "caloric_split": {"fat": pct_fat, "sugar": pct_sugar, "protein": pct_protein},
    }


@router.get("/nutrition-trends")
def get_nutrition_trends(
    time_range: str = "6m",
    nutrient_type: str = "sugar",  # sodium, fat, sugar, protein
    db: Session = Depends(get_db),
):
    """
    Returns weekly nutritional intake broken down by item.
    Returns Top 8 items for the selected nutrient, others grouped.
    """
    from collections import defaultdict

    results, _ = _get_nutrition_data(time_range, db)

    # Intermediate storage: {week: {item_name: total_value}}
    data_map: defaultdict[str, defaultdict[str, float]] = defaultdict(lambda: defaultdict(float))
    all_weeks = set()
    item_totals: defaultdict[str, float] = defaultdict(float)  # To find top items overall

    is_sodium = nutrient_type == "sodium"

    for r in results:
        week = r["week"]
        all_weeks.add(week)
        item_name = r["item_name"]

        if nutrient_type == "sodium":
            val = r["sodium"]
        elif nutrient_type == "fat":
            val = r["fat"]
        elif nutrient_type == "sugar":
            val = r["sugar"]
        elif nutrient_type == "protein":
            val = r["protein"]
        else:
            val = 0.0

        data_map[week][item_name] += val
        item_totals[item_name] += val

    # 3. Determine Top Items to keep as separate stacks
    sorted_weeks = sorted(all_weeks)
    top_items = sorted(item_totals.items(), key=lambda x: x[1], reverse=True)[:8]
    top_item_names = [x[0] for x in top_items]

    # 4. Prepare Chart.js datasets
    datasets = []
    # Palette for items
    colors = [
        "#3b82f6",
        "#ef4444",
        "#10b981",
        "#f59e0b",
        "#8b5cf6",
        "#ec4899",
        "#06b6d4",
        "#f97316",
        "#64748b",
    ]

    for i, name in enumerate(top_item_names):
        item_data = []
        for week in sorted_weeks:
            item_data.append(round(data_map[week].get(name, 0), 1))

        datasets.append(
            {
                "label": name,
                "data": item_data,
                "backgroundColor": colors[i % len(colors)],
                "stack": "stack0",
            }
        )

    # Add "Others" stack
    others_data = []
    for week in sorted_weeks:
        week_total = sum(data_map[week].values())
        top_sum = sum(data_map[week].get(name, 0) for name in top_item_names)
        others_data.append(round(max(0, week_total - top_sum), 1))

    if any(v > 0 for v in others_data):
        datasets.append(
            {
                "label": "Others",
                "data": others_data,
                "backgroundColor": "#94a3b8",
                "stack": "stack0",
            }
        )

    return {"labels": sorted_weeks, "datasets": datasets, "unit": "mg" if is_sodium else "g"}
