import re
from collections import Counter
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import extract, func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Category, Item, Receipt, ReceiptItem, Store
from app.models.exclusion import ExclusionRule
from app.services.nutrition_utils import calculate_receipt_item_macros, determine_macro_dominant
from app.services.spend import LINE_TOTAL, line_total, unit_price_of

router = APIRouter()


def _get_analytics_exclusions(db: Session) -> list[str]:
    """Return lowercase patterns excluded from analytics.

    Patterns are matched as case-insensitive substrings against both
    category names *and* item names (see ``_is_excluded``).
    """
    rules = db.query(ExclusionRule).filter(ExclusionRule.scope == "analytics").all()
    if rules:
        return [r.pattern.lower() for r in rules]
    # Fallback to defaults if table is empty
    return ["excluded", "other", "taxes & fees"]


def _is_excluded(exclusions: list[str], cat_name: str, item_name: str = "") -> bool:
    """Return True if *cat_name* or *item_name* matches any exclusion pattern.

    Matching is case-insensitive substring (same rule the Settings UI
    describes).  This ensures patterns that are item names — e.g.
    ``"CRV"`` — work even when the item's category is something generic
    like "Other" or "Fees & Taxes".
    """
    cat_lower = cat_name.lower()
    item_lower = item_name.lower()
    return any(ex in cat_lower or (item_lower and ex in item_lower) for ex in exclusions)


@router.get("/ingredient-stats")
def ingredient_stats(db: Session = Depends(get_db)):
    """Aggregate top 25 ingredients from items with FDC data"""
    items = db.query(Item).filter(Item.ingredients.isnot(None)).all()

    all_ingredients = []
    # Regex to split by commas but ignore commas inside parentheses
    # and clean up noise like (10%), [ORGANIC], etc.
    split_pattern = re.compile(r",(?![^\(]*\))")
    clean_pattern = re.compile(r"[\(\[\d\.%\]\)]")

    for item in items:
        if not item.ingredients:
            continue

        # Split by comma (ignoring commas in parentheses)
        parts = split_pattern.split(item.ingredients)
        for p in parts:
            # Basic cleanup: uppercase, strip whitespace, remove some common noise
            clean = p.upper().strip()
            # Remove percentages and brackets
            clean = clean_pattern.sub("", clean)
            # Remove leading/trailing non-alpha
            clean = re.sub(r"^[^A-Z]+|[^A-Z]+$", "", clean)

            if len(clean) > 2 and clean not in ["INGREDIENTS", "CONTAINS", "AND", "OR", "WATER"]:
                all_ingredients.append(clean)

    counts = Counter(all_ingredients).most_common(25)

    return {"labels": [c[0] for c in counts], "data": [c[1] for c in counts]}


@router.get("/spending-by-category")
def spending_by_category(
    start_date: str | None = None,
    end_date: str | None = None,
    db: Session = Depends(get_db),
):
    """Get total spending by category"""

    query = (
        db.query(
            Category.name,
            func.sum(LINE_TOTAL).label("total"),
        )
        .join(Item, Category.id == Item.category_id)
        .join(ReceiptItem, Item.id == ReceiptItem.item_id)
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
    )

    # Apply date filters
    if start_date:
        query = query.filter(Receipt.purchase_date >= start_date)
    if end_date:
        # Add 1 day to end_date to include the full day
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        query = query.filter(Receipt.purchase_date < end_dt)

    results = (
        query.filter(
            Category.name.notin_(
                ["Excluded", "Other", "Fees & Taxes", "CRV (tax)", "Non-Alcoholic Beer"]
            )
        )
        .group_by(Category.id, Category.name)
        .order_by(func.sum(LINE_TOTAL).desc())
        .all()
    )

    return {
        "labels": [r[0] for r in results],
        "data": [float(r[1] or 0) for r in results],
    }


@router.get("/monthly-spending")
def monthly_spending(months: int = 6, db: Session = Depends(get_db)):
    """Get spending by month for the last N months"""
    from dateutil.relativedelta import relativedelta

    now = datetime.now()
    # Start from the 1st day of the month, N-1 months ago
    start_date = (now - relativedelta(months=months - 1)).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )

    results = (
        db.query(Receipt.purchase_date, func.sum(LINE_TOTAL))
        .join(ReceiptItem, Receipt.id == ReceiptItem.receipt_id)
        .join(Item, ReceiptItem.item_id == Item.id)
        .outerjoin(Category, Item.category_id == Category.id)
        .filter(Receipt.purchase_date >= start_date)
        .filter(
            or_(
                Category.name.is_(None),
                Category.name.notin_(
                    ["Excluded", "Other", "Fees & Taxes", "CRV (tax)", "Non-Alcoholic Beer"]
                ),
            )
        )
        .group_by(Receipt.purchase_date)
        .all()
    )

    monthly_totals = {}
    for date, amount in results:
        if date is None:
            continue
        month_str = date.strftime("%Y-%m")
        monthly_totals[month_str] = monthly_totals.get(month_str, 0) + float(amount or 0)

    final_labels = []
    final_data = []

    for i in range(months - 1, -1, -1):
        m = now - relativedelta(months=i)
        m_str = m.strftime("%Y-%m")
        label = m.strftime("%b %Y")  # e.g., "Oct 2023"
        final_labels.append(label)
        final_data.append(monthly_totals.get(m_str, 0.0))

    return {"labels": final_labels, "data": final_data}


@router.get("/weekly-spending")
def weekly_spending(weeks: int = 12, db: Session = Depends(get_db)):
    """Get total spending by week for the last N weeks (Tufte style data source)"""
    start_date = datetime.now() - timedelta(weeks=weeks)

    results = (
        db.query(Receipt.purchase_date, func.sum(LINE_TOTAL))
        .join(ReceiptItem, Receipt.id == ReceiptItem.receipt_id)
        .join(Item, ReceiptItem.item_id == Item.id)
        .outerjoin(Category, Item.category_id == Category.id)
        .filter(Receipt.purchase_date >= start_date)
        .filter(
            or_(
                Category.name.is_(None),
                Category.name.notin_(
                    ["Excluded", "Other", "Fees & Taxes", "CRV (tax)", "Non-Alcoholic Beer"]
                ),
            )
        )
        .group_by(Receipt.purchase_date)
        .all()
    )

    weekly_totals = {}
    for date, amount in results:
        if date is None:
            continue
        # Group by Monday of that week
        week_start = date - timedelta(days=date.weekday())
        week_str = week_start.strftime("%Y-%m-%d")
        weekly_totals[week_str] = weekly_totals.get(week_str, 0) + float(amount or 0)

    final_labels = []
    final_data = []

    now = datetime.now()
    this_week_start = now - timedelta(days=now.weekday())

    for i in range(weeks - 1, -1, -1):
        wk = this_week_start - timedelta(weeks=i)
        wk_str = wk.strftime("%Y-%m-%d")
        label = wk.strftime("%b %d")  # e.g. "Oct 09"
        final_labels.append(label)
        final_data.append(weekly_totals.get(wk_str, 0.0))

    return {"labels": final_labels, "data": final_data}


@router.get("/price-trends/{item_id}")
def price_trends(item_id: int, db: Session = Depends(get_db)):
    """Get detailed purchase history for a specific item"""

    results = (
        db.query(Receipt.purchase_date, ReceiptItem.price, Store.name, Receipt.id)
        .join(ReceiptItem, Receipt.id == ReceiptItem.receipt_id)
        .join(Store, Receipt.store_id == Store.id)
        .filter(ReceiptItem.item_id == item_id)
        .order_by(Receipt.purchase_date.asc())
        .distinct()
        .all()
    )

    # Return structured list for stacked bar chart, filtering out missing dates
    return [
        {
            "date": r[0].strftime("%Y-%m-%d"),
            "price": float(r[1]),
            "store": r[2],
            "receipt_id": r[3],
        }
        for r in results
        if r[0] is not None
    ]


@router.get("/store-comparison")
def store_comparison(
    start_date: str | None = None,
    end_date: str | None = None,
    db: Session = Depends(get_db),
):
    """Compare total spending by store"""

    query = (
        db.query(
            Store.name,
            func.sum(LINE_TOTAL).label("total"),
            func.count(func.distinct(Receipt.id)).label("receipt_count"),
        )
        .join(Receipt, Store.id == Receipt.store_id)
        .join(ReceiptItem, Receipt.id == ReceiptItem.receipt_id)
        .join(Item, ReceiptItem.item_id == Item.id)
        .outerjoin(Category, Item.category_id == Category.id)
        .filter(
            or_(
                Category.name.is_(None),
                Category.name.notin_(
                    ["Excluded", "Other", "Fees & Taxes", "CRV (tax)", "Non-Alcoholic Beer"]
                ),
            )
        )
    )

    # Apply date filters
    if start_date:
        query = query.filter(Receipt.purchase_date >= start_date)
    if end_date:
        # Add 1 day to end_date to include the full day
        end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        query = query.filter(Receipt.purchase_date < end_dt)

    results = (
        query.group_by(Store.id, Store.name).order_by(func.sum(Receipt.total_amount).desc()).all()
    )

    return {
        "labels": [r[0] for r in results],
        "spending": [float(r[1] or 0) for r in results],
        "receipts": [int(r[2]) for r in results],
    }


@router.get("/price-alerts")
def price_alerts(threshold: float = 10.0, db: Session = Depends(get_db)):
    """Find items with significant price increases"""

    # Get items with at least 2 purchases
    items_with_history = (
        db.query(Item.id, Item.name, Category.name.label("category_name"))
        .join(ReceiptItem, Item.id == ReceiptItem.item_id)
        .outerjoin(Category, Item.category_id == Category.id)
        .group_by(Item.id, Item.name, Category.name)
        .having(func.count(ReceiptItem.id) >= 2)
        .all()
    )

    alerts = []

    for item_id, item_name, category_name in items_with_history:
        # Get price history
        prices = (
            db.query(Receipt.purchase_date, ReceiptItem.price)
            .join(ReceiptItem, Receipt.id == ReceiptItem.receipt_id)
            .filter(ReceiptItem.item_id == item_id)
            .order_by(Receipt.purchase_date.desc())
            .limit(10)
            .all()
        )

        if len(prices) < 2:
            continue

        # Compare most recent price to previous
        current_price = float(prices[0][1])
        previous_price = float(prices[1][1])

        if previous_price > 0:
            percent_change = ((current_price - previous_price) / previous_price) * 100

            if abs(percent_change) >= threshold:
                alerts.append(
                    {
                        "item_id": item_id,
                        "item_name": item_name,
                        "category": category_name or "Other",
                        "previous_price": previous_price,
                        "current_price": current_price,
                        "percent_change": round(percent_change, 1),
                        "last_purchase": prices[0][0].strftime("%Y-%m-%d"),
                    }
                )

    # Sort by percent change (highest first)
    alerts.sort(key=lambda x: abs(x["percent_change"]), reverse=True)

    return alerts


@router.get("/top-items")
def top_items(limit: int = 10, db: Session = Depends(get_db)):
    """Get top items by total spending"""

    results = (
        db.query(
            Item.name,
            Category.name.label("category_name"),
            func.sum(LINE_TOTAL).label("total_spent"),
            func.count(ReceiptItem.id).label("purchase_count"),
        )
        .join(ReceiptItem, Item.id == ReceiptItem.item_id)
        .outerjoin(Category, Item.category_id == Category.id)
        .filter(
            or_(
                Category.name.is_(None),
                Category.name.notin_(
                    ["Excluded", "Other", "Fees & Taxes", "CRV (tax)", "Non-Alcoholic Beer"]
                ),
            )
        )
        .group_by(Item.id, Item.name, Category.name)
        .order_by(func.sum(LINE_TOTAL).desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "name": r[0],
            "category": r[1] or "Other",
            "total_spent": float(r[2] or 0),
            "purchase_count": int(r[3]),
        }
        for r in results
    ]


@router.get("/summary")
def summary_stats(db: Session = Depends(get_db)):
    """Get overall summary statistics"""

    # Total spending
    total_spending = (
        db.query(func.sum(LINE_TOTAL))
        .join(Item, ReceiptItem.item_id == Item.id)
        .outerjoin(Category, Item.category_id == Category.id)
        .filter(
            or_(
                Category.name.is_(None),
                Category.name.notin_(
                    ["Excluded", "Other", "Fees & Taxes", "CRV (tax)", "Non-Alcoholic Beer"]
                ),
            )
        )
        .scalar()
        or 0
    )

    # Total receipts
    total_receipts = db.query(func.count(Receipt.id)).scalar() or 0

    # Total items tracked
    total_items = db.query(func.count(Item.id)).scalar() or 0

    # Average receipt amount
    avg_receipt = total_spending / total_receipts if total_receipts > 0 else 0

    # This month spending
    start_of_month = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    this_month = (
        db.query(func.sum(LINE_TOTAL))
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .join(Item, ReceiptItem.item_id == Item.id)
        .outerjoin(Category, Item.category_id == Category.id)
        .filter(Receipt.purchase_date >= start_of_month)
        .filter(
            or_(
                Category.name.is_(None),
                Category.name.notin_(
                    ["Excluded", "Other", "Fees & Taxes", "CRV (tax)", "Non-Alcoholic Beer"]
                ),
            )
        )
        .scalar()
        or 0
    )

    return {
        "total_spending": float(total_spending),
        "total_receipts": int(total_receipts),
        "total_items": int(total_items),
        "avg_receipt": float(avg_receipt),
        "this_month": float(this_month),
    }


# HTML Endpoints for Dashboard Tables


@router.get("/store-history/{store_id}")
def store_spending_history(store_id: int, db: Session = Depends(get_db)):
    """Get spending history for a specific store"""
    results = (
        db.query(Receipt.purchase_date, func.sum(LINE_TOTAL))
        .join(ReceiptItem, Receipt.id == ReceiptItem.receipt_id)
        .join(Item, ReceiptItem.item_id == Item.id)
        .outerjoin(Category, Item.category_id == Category.id)
        .filter(Receipt.store_id == store_id)
        .filter(
            or_(
                Category.name.is_(None),
                Category.name.notin_(
                    ["Excluded", "Other", "Fees & Taxes", "CRV (tax)", "Non-Alcoholic Beer"]
                ),
            )
        )
        .group_by(Receipt.purchase_date)
        .order_by(Receipt.purchase_date)
        .all()
    )

    # Aggregate by day to avoid messy graphs
    daily_totals = {}
    for date, amount in results:
        date_str = date.strftime("%Y-%m-%d")
        daily_totals[date_str] = daily_totals.get(date_str, 0) + float(amount)

    sorted_dates = sorted(daily_totals.keys())

    return {"labels": sorted_dates, "data": [daily_totals[d] for d in sorted_dates]}


# --- Best Value Logic Refactor ---


def _get_top_items(db: Session, limit: int = 10):
    """Helper: Get the IDs of the top N most frequently purchased items."""
    results = (
        db.query(Item.id)
        .join(ReceiptItem, Item.id == ReceiptItem.item_id)
        .group_by(Item.id)
        .order_by(func.count(ReceiptItem.id).desc())
        .limit(limit)
        .all()
    )
    return [r[0] for r in results]


@router.get("/basket-over-time")
def basket_over_time(limit: int = 10, db: Session = Depends(get_db)):
    """
    Calculate the total cost of a 'Shopping Basket' of top items over time.
    Groups by month. Carries forward the last known price for missing months.
    """
    top_item_ids = _get_top_items(db, limit)

    if not top_item_ids:
        return {"labels": [], "data": []}

    # Fetch all purchase history for these top items, ordered by date
    history = (
        db.query(
            ReceiptItem.item_id,
            ReceiptItem.price,
            ReceiptItem.quantity,
            extract("year", Receipt.purchase_date).label("year"),
            extract("month", Receipt.purchase_date).label("month"),
            Receipt.purchase_date,
        )
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .filter(ReceiptItem.item_id.in_(top_item_ids))
        .order_by(Receipt.purchase_date.asc())
        .all()
    )

    if not history:
        return {"labels": [], "data": []}

    # Organize data by month
    months_set = set()
    monthly_prices = {}  # {(year, month): {item_id: avg_unit_price}}

    for item_id, price, qty, year, month, _date in history:
        if year is None or month is None:
            continue
        year = int(year)
        month = int(month)
        months_set.add((year, month))

        unit_price = unit_price_of(price, qty)

        if (year, month) not in monthly_prices:
            monthly_prices[(year, month)] = {}

        # If multiple purchases in a month, we'll just take the latest one (since we ordered by date asc)
        # or we could average them. Taking latest is simpler.
        monthly_prices[(year, month)][item_id] = float(unit_price)

    sorted_months = sorted(months_set)

    # Fill in missing data (carry forward)
    last_known_prices = {}  # {item_id: price}
    basket_totals = []
    labels = []

    # Optimized: pre-caching earliest known prices once outside the loop (Fixed Audit #8.66)
    earliest_known_prices = {}
    for (_y, _m), prices in monthly_prices.items():
        for i_id, p in prices.items():
            if i_id not in earliest_known_prices:
                earliest_known_prices[i_id] = p
            # Logic to ensure it is actually earliest (monthly_prices is already chronologically populated
            # due to history sort, so the first time we see an item_id, it is the earliest)

    for year, month in sorted_months:
        current_month_prices = monthly_prices.get((year, month), {})

        # Update our running knowledge of prices
        for item_id in top_item_ids:
            if item_id in current_month_prices:
                last_known_prices[item_id] = current_month_prices[item_id]

        # Calculate basket total for this month using latest known prices
        month_total = 0
        for item_id in top_item_ids:
            if item_id in last_known_prices:
                month_total += last_known_prices[item_id]
            elif item_id in earliest_known_prices:
                month_total += earliest_known_prices[item_id]

        month_name = datetime(year, month, 1).strftime("%b %Y")
        labels.append(month_name)
        basket_totals.append(round(month_total, 2))

    # Get truncated names for the top items
    top_item_names = []
    if top_item_ids:
        # Maintain order of top_item_ids
        item_map = {i.id: i.name for i in db.query(Item).filter(Item.id.in_(top_item_ids)).all()}
        for i_id in top_item_ids:
            name = item_map.get(i_id, "Unknown")
            # Truncate: take first 2 words or max 15 chars
            truncated = " ".join(name.split()[:2])
            if len(truncated) > 15:
                truncated = truncated[:12] + "..."
            top_item_names.append(truncated)

    return {"labels": labels, "data": basket_totals, "items": top_item_names}


@router.get("/sub-category-trends")
def get_sub_category_trends(db: Session = Depends(get_db)):
    """
    Get spending over time for specific keywords:
    Beef, Chicken, Fish, Lamb, Milk, Fruit, Vegetables
    """
    keywords = ["Beef", "Chicken", "Fish", "Lamb", "Milk", "Fruit", "Vegetables"]

    # Get all receipts with items
    results = (
        db.query(
            Item.name,
            ReceiptItem.price,
            ReceiptItem.quantity,
            extract("year", Receipt.purchase_date).label("year"),
            extract("month", Receipt.purchase_date).label("month"),
        )
        .join(ReceiptItem, Item.id == ReceiptItem.item_id)
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .outerjoin(Category, Item.category_id == Category.id)
        .filter(
            or_(
                Category.name.is_(None),
                Category.name.notin_(
                    ["Excluded", "Other", "Fees & Taxes", "CRV (tax)", "Non-Alcoholic Beer"]
                ),
            )
        )
        .order_by(Receipt.purchase_date.asc())
        .all()
    )

    # Process into trends
    # trends: keyword -> {(year, month): total_spent}
    trends = {k: {} for k in keywords}
    all_months = set()

    for name, price, qty, year, month in results:
        if year is None or month is None:
            continue
        year, month = int(year), int(month)
        all_months.add((year, month))

        name_lower = name.lower()
        spent = (price * qty) if price and qty else 0

        for k in keywords:
            if k.lower() in name_lower:
                month_key = (year, month)
                trends[k][month_key] = trends[k].get(month_key, 0) + float(spent)

    sorted_months = sorted(all_months)
    labels = [datetime(y, m, 1).strftime("%b %Y") for y, m in sorted_months]

    datasets = []
    for k in keywords:
        data = [round(trends[k].get(m, 0), 2) for m in sorted_months]
        datasets.append({"label": k, "data": data})

    return {"labels": labels, "datasets": datasets}


@router.get("/widgets/top-combo-timeseries")
def get_top_combo_timeseries(db: Session = Depends(get_db)):
    """
    Find the top 8 (Category, Store) pairs by receipt count, and return
    the total spent for that category per receipt over time for each.
    """
    from sqlalchemy import func

    # 1. Find the top 8 (Category, Store) pairs by receipt count
    # We look for the most recurring shopping habits
    top_pairs = (
        db.query(
            Category.id,
            Category.name,
            Store.id,
            Store.name,
            func.count(func.distinct(Receipt.id)).label("r_count"),
        )
        .join(Item, Category.id == Item.category_id)
        .join(ReceiptItem, Item.id == ReceiptItem.item_id)
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .join(Store, Receipt.store_id == Store.id)
        .group_by(Category.id, Store.id)
        .order_by(func.count(func.distinct(Receipt.id)).desc())
        .limit(8)
        .all()
    )

    if not top_pairs:
        return []

    all_combos_data = []

    for cat_id, cat_name, store_id, store_name, _ in top_pairs:
        # 2. Fetch history for this pair
        # Summing up all items in that category for each receipt
        history = (
            db.query(
                Receipt.purchase_date,
                func.sum(LINE_TOTAL).label("spent"),
            )
            .join(ReceiptItem, Receipt.id == ReceiptItem.receipt_id)
            .join(Item, ReceiptItem.item_id == Item.id)
            .filter(Item.category_id == cat_id)
            .filter(Receipt.store_id == store_id)
            .group_by(Receipt.id)
            .order_by(Receipt.purchase_date.asc())
            .all()
        )

        labels = [h[0].strftime("%b %d, %Y") if h[0] else "Unknown Date" for h in history]
        data = [float(h[1]) for h in history]

        all_combos_data.append(
            {"category_name": cat_name, "store_name": store_name, "labels": labels, "data": data}
        )

    return all_combos_data


@router.get("/random-category-item-trends")
def get_random_category_item_trends(db: Session = Depends(get_db)):
    """
    Randomly select 4 categories and their top items for dashboard visualization.
    """
    import random

    # 1. Get categories that have at least 8 items with at least 2 purchases
    # We use a subquery to find suitable items first
    suitable_items_query = (
        db.query(Item.id)
        .join(ReceiptItem, Item.id == ReceiptItem.item_id)
        .group_by(Item.id)
        .having(func.count(ReceiptItem.id) >= 2)
    )

    categories_with_data = (
        db.query(Category.id, Category.name)
        .join(Item, Category.id == Item.category_id)
        .filter(Item.id.in_(suitable_items_query))
        .filter(
            Category.name.notin_(
                ["Excluded", "Other", "Fees & Taxes", "CRV (tax)", "Non-Alcoholic Beer"]
            )
        )
        .group_by(Category.id, Category.name)
        .having(func.count(Item.id) >= 5)
        .all()
    )

    if not categories_with_data:
        return []

    # Pick 4 random categories (or all if less than 4)
    selected_categories = random.sample(categories_with_data, min(len(categories_with_data), 4))

    all_charts_data = []

    for cat_id, cat_name in selected_categories:
        # 2. Get top 6 items for this category (by purchase count)
        top_items = (
            db.query(Item.id, Item.name)
            .join(ReceiptItem, Item.id == ReceiptItem.item_id)
            .filter(Item.category_id == cat_id)
            .filter(Item.id.in_(suitable_items_query))
            .group_by(Item.id, Item.name)
            .order_by(func.count(ReceiptItem.id).desc())
            .limit(6)
            .all()
        )

        item_datasets = []
        # We need to collect all dates to create a unified X-axis for the chart
        all_dates = set()
        item_histories = {}

        for item_id, item_name in top_items:
            # Fetch price history for this item
            history = (
                db.query(Receipt.purchase_date, ReceiptItem.price, ReceiptItem.quantity)
                .join(ReceiptItem, Receipt.id == ReceiptItem.receipt_id)
                .filter(ReceiptItem.item_id == item_id)
                .order_by(Receipt.purchase_date.asc())
                .all()
            )

            prices_by_date = {}
            for date, price, qty in history:
                if not date:
                    continue
                date_str = date.strftime("%Y-%m-%d")
                all_dates.add(date_str)
                unit_price = unit_price_of(price, qty)
                prices_by_date[date_str] = unit_price

            item_histories[item_name] = prices_by_date

        # Sort dates for the X-axis
        sorted_dates = sorted(all_dates)

        # Build datasets (carrying forward last price for missing dates to avoid gaps)
        for item_name, history in item_histories.items():
            data_points = []
            last_price = None
            for d in sorted_dates:
                if d in history:
                    last_price = history[d]
                data_points.append(last_price)

            item_datasets.append({"label": item_name, "data": data_points})

        all_charts_data.append(
            {"category_name": cat_name, "labels": sorted_dates, "datasets": item_datasets}
        )

    return all_charts_data


@router.get("/ocr-accuracy")
def get_ocr_accuracy(db: Session = Depends(get_db)):
    """Calculate an aggregate OCR accuracy score for completed PDF receipts."""
    from app.models import Receipt

    pdf_receipts = (
        db.query(Receipt)
        .filter(Receipt.image_path.like("%.pdf"), Receipt.status == "completed")
        .all()
    )

    if not pdf_receipts:
        return {"score": 0.0, "total_receipts": 0}

    scores = []
    for r in pdf_receipts:
        items = r.items
        item_count = len(items)
        junk_score = 0
        if item_count > 0:
            for item in items:
                name = item.item.name if item.item else ""
                if len(name) > 60:
                    junk_score += 1
                if any(
                    x in name.lower()
                    for x in [
                        "http",
                        "www",
                        "click",
                        "privacy",
                        "terms",
                        "account",
                        "order",
                        "subtotal",
                        "total",
                        "tax",
                        "shipping",
                    ]
                ):
                    junk_score += 1
            quality = max(1, 10 - int((junk_score / max(item_count, 1)) * 10))
        else:
            quality = 1
        scores.append(quality)

    avg = sum(scores) / len(scores)
    # Round to nearest 0.5
    rounded_score = round(avg * 2) / 2
    return {"score": rounded_score, "total_receipts": len(scores)}


@router.get("/bi-dashboard")
def get_bi_dashboard_data(db: Session = Depends(get_db)):
    """Aggregate live calculations for the Tufte BI Dashboard."""
    # Time window: Last 30 days
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)

    receipts = (
        db.query(Receipt)
        .filter(Receipt.purchase_date >= thirty_days_ago, Receipt.status == "completed")
        .all()
    )

    exclusions = _get_analytics_exclusions(db)

    total_spend = 0.0
    macro_spend = {
        "Protein-dominant": 0.0,
        "Carb-dominant": 0.0,
        "Fat-dominant": 0.0,
        "Mixed macro": 0.0,
        "Non-nutritive / Other": 0.0,
        "Missing USDA Data": 0.0,
    }

    protein_sources = []
    category_metrics = {}

    for r in receipts:
        for ri in r.items:
            # Skip exclusions
            cat_name = ri.item.category.name if ri.item and ri.item.category else "Uncategorized"
            item_name = ri.item.name if ri.item else ""
            if _is_excluded(exclusions, cat_name, item_name):
                continue

            item_spend = line_total(ri)
            total_spend += item_spend

            if cat_name not in category_metrics:
                category_metrics[cat_name] = {"spend": 0, "protein_g": 0, "carbs_g": 0, "kcal": 0}
            category_metrics[cat_name]["spend"] += item_spend

            # Check macros
            macros = calculate_receipt_item_macros(ri)
            if macros:
                dominant = determine_macro_dominant(macros)
                macro_spend[dominant] += item_spend

                category_metrics[cat_name]["protein_g"] += macros.get("protein_g", 0)
                category_metrics[cat_name]["carbs_g"] += macros.get("carbs_g", 0)
                category_metrics[cat_name]["kcal"] += macros.get("energy_kcal", 0)

                # Protein ROI
                if macros.get("protein_g", 0) > 5 and item_spend > 0:
                    cpp = item_spend / macros["protein_g"]
                    protein_sources.append(
                        {
                            "id": ri.item.id if ri.item else None,
                            "name": f"{ri.item.name} ({r.store.name if r.store else 'Unknown'})",
                            "cpp": cpp,
                        }
                    )
            else:
                macro_spend["Missing USDA Data"] += item_spend

    # Format Macro Breakdown
    bi_macro = []
    colors = {
        "Protein-dominant": "#10b981",
        "Carb-dominant": "#f59e0b",
        "Fat-dominant": "#3b82f6",
        "Mixed macro": "#8b5cf6",
        "Non-nutritive / Other": "#6b7280",
        "Missing USDA Data": "#ef4444",
    }

    examples = {
        "Protein-dominant": "Eggs, Greek Yogurt, Chicken",
        "Carb-dominant": "Bread, Rice, Pasta, Fruit",
        "Fat-dominant": "Cheese, Nuts, Olive Oil",
        "Mixed macro": "Avocado, Whole Milk, Salmon",
        "Non-nutritive / Other": "Coffee, Spices, Paper Goods",
        "Missing USDA Data": "Items without FDC data matched",
    }

    valid_spend = sum(macro_spend.values())
    if valid_spend > 0:
        for k, v in macro_spend.items():
            if v > 0:
                bi_macro.append(
                    {
                        "label": k,
                        "color": colors.get(k, "#6b7280"),
                        "pct": round((v / valid_spend) * 100),
                        "spend": round(v, 2),
                        "examples": examples.get(k, ""),
                    }
                )

    # Sort ROI best first
    protein_sources.sort(key=lambda x: x["cpp"])
    # Deduplicate by item name to show variety
    seen_roi = set()
    unique_roi = []
    for p in protein_sources:
        if p["name"] not in seen_roi:
            seen_roi.add(p["name"])
            unique_roi.append(p)

    bi_roi = unique_roi[:10]

    # Efficiency Matrix
    bi_cats = []
    for k, v in category_metrics.items():
        if v["spend"] > 0:
            cpp = v["spend"] / v["protein_g"] if v["protein_g"] > 0 else None
            cpc = v["spend"] / v["carbs_g"] if v["carbs_g"] > 0 else None
            cpcal = v["spend"] / v["kcal"] if v["kcal"] > 0 else None

            bi_cats.append(
                {"name": k, "cpp": cpp, "cpc": cpc, "cpcal": cpcal, "spend": round(v["spend"], 2)}
            )

    bi_cats.sort(key=lambda x: x["spend"], reverse=True)

    from app.api.settings_router import _load_feature_flags

    protein_roi_target = _load_feature_flags().get("protein_roi_target", 0.20)

    return {
        "kpis": {
            "monthly_spend": round(total_spend, 2),
            "avg_daily_spend": round(total_spend / 30, 2),
            "nutrition_score": 0,  # Placeholder for now
        },
        "macro_breakdown": sorted(bi_macro, key=lambda x: x["pct"], reverse=True),
        "protein_roi": bi_roi,
        "protein_roi_target": protein_roi_target,
        "efficiency": bi_cats[:8],
        "categories": bi_cats,
    }
