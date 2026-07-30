from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.trends_nutrition import (
    _get_nutrition_data,
    get_macronutrient_calories_data,
    get_nutrition_coverage,
    get_nutrition_density_data,
    get_nutrition_multiples_data,
    get_nutrition_trends,
    get_usda_product_types,
)
from app.database import get_db
from app.models import Item, Receipt, ReceiptItem

router = APIRouter()


@router.get("/data")
def get_trends_data(time_range: str = "year", db: Session = Depends(get_db)):
    """
    Get stacked bar chart data for category spending over time (weekly).
    Returns:
    {
        datasets: [ { label: 'Category Name', data: [...], stack: 'Stack 0' } ],
        labels: ['2023-W01', ...]
    }
    """
    from datetime import datetime, timedelta

    end_date = datetime.now()
    if time_range == "year":
        start_date = end_date - timedelta(days=365)
    elif time_range == "6m":
        start_date = end_date - timedelta(days=180)
    elif time_range == "ytd":
        start_date = datetime(end_date.year, 1, 1)
    else:
        start_date = None

    # 2. Query Data: Sum cost group by Week and Category
    # PostgreSQL: date_trunc('week', purchase_date)

    # We need to join ReceiptItem -> Receipt -> Item -> Category
    # If category is None, we can label as 'Uncategorized'

    from app.models import Category

    query = (
        db.query(
            func.strftime("%Y-%W", Receipt.purchase_date).label("week"),
            Item.category_id,
            func.sum(ReceiptItem.price * ReceiptItem.quantity).label("total_cost"),
        )
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .join(Item, ReceiptItem.item_id == Item.id)
        .outerjoin(Category, Item.category_id == Category.id)
        .filter(
            or_(
                Category.name.is_(None),
                Category.name.notin_(["Excluded", "Other", "Fees & Taxes", "Non-Alcoholic Beer"]),
            )
        )
    )

    if start_date:
        query = query.filter(Receipt.purchase_date >= start_date)

    results = query.group_by("week", Item.category_id).order_by("week").all()

    # 3. Process Categories Mapping
    from app.models import Category

    categories = db.query(Category).all()
    cat_map = {c.id: c.name for c in categories}
    cat_map[None] = "Uncategorized"

    # 4. Structure Data
    # We need a unified list of weeks (X-axis labels)
    weeks = sorted({r.week for r in results if r.week})
    # SQLite returns string 'YYYY-WW', simple sort works
    labels = weeks

    # Initialize datasets for each category that appears in results
    active_cat_ids = {r.category_id for r in results}
    datasets = {}

    # Define colors
    colors = [
        "#3b82f6",
        "#ef4444",
        "#10b981",
        "#f59e0b",
        "#8b5cf6",
        "#ec4899",
        "#6366f1",
        "#14b8a6",
        "#f97316",
        "#84cc16",
        "#64748b",
        "#d946ef",
    ]

    for i, cat_id in enumerate(active_cat_ids):
        cat_name = cat_map.get(cat_id, "Unknown")
        color = colors[i % len(colors)]

        # Initialize data array with 0s for all weeks
        data_points = [0.0] * len(weeks)
        datasets[cat_id] = {
            "label": cat_name,
            "data": data_points,
            "backgroundColor": color,
            "stack": "Stack 0",
        }

    # Fill data
    for row in results:
        if not row.week:
            # Receipts with no purchase_date produce a None week; they were
            # already excluded from the axis above
            continue
        w_idx = weeks.index(row.week)
        c_id = row.category_id
        if c_id in datasets:
            datasets[c_id]["data"][w_idx] = float(row.total_cost)

    return {"labels": labels, "datasets": list(datasets.values())}


@router.get("/category-stats")
def get_category_stats(db: Session = Depends(get_db)):
    """
    Get detailed stats for each category:
    - Where to buy (Store comparison)
    - Historical trend (Line chart data)
    - Last seen dates
    """
    from datetime import datetime, timedelta

    from sqlalchemy import func

    from app.models import Category, Item, Receipt, ReceiptItem, Store

    # 1. Setup Time Ranges
    now = datetime.now()
    six_months_ago = now - timedelta(days=180)
    ninety_days_ago = now - timedelta(days=90)

    # 2. Get Categories
    categories = db.query(Category).all()

    # 3. Fetch Category-Store Stats (Last 90 days for 'Where to buy')
    # Use normalized price if available (from metadata logic in analytics)
    # For now, let's use weighted average price per item
    store_stats_query = (
        db.query(
            Item.category_id,
            Store.id.label("store_id"),
            Store.name.label("store_name"),
            func.max(Receipt.purchase_date).label("last_seen"),
            func.sum(ReceiptItem.price * ReceiptItem.quantity).label("total_spent"),
            func.sum(ReceiptItem.quantity).label("total_qty"),
        )
        .join(ReceiptItem, Item.id == ReceiptItem.item_id)
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .join(Store, Receipt.store_id == Store.id)
        .filter(Receipt.purchase_date >= ninety_days_ago)
        .group_by(Item.category_id, Store.id, Store.name)
        .all()
    )

    store_lookup = {}
    for row in store_stats_query:
        cat_id = row.category_id
        if cat_id not in store_lookup:
            store_lookup[cat_id] = []

        last_seen_dt = row.last_seen
        days_ago = (now - last_seen_dt).days

        # Format "Last seen" string
        if days_ago == 0:
            last_seen_str = "Today"
        elif days_ago == 1:
            last_seen_str = "Yesterday"
        elif days_ago < 7:
            last_seen_str = f"{days_ago} days ago"
        elif days_ago < 30:
            weeks = days_ago // 7
            last_seen_str = f"{weeks} wk{'s' if weeks > 1 else ''} ago"
        else:
            months = days_ago // 30
            last_seen_str = f"{months} mo{'s' if months > 1 else ''} ago"

        avg_price = float(row.total_spent / row.total_qty) if row.total_qty > 0 else 0

        store_lookup[cat_id].append(
            {
                "id": row.store_id,
                "name": row.store_name,
                "last_seen": last_seen_str,
                "avg_price": round(avg_price, 2),
                "is_best_price": False,  # Will set later
            }
        )

    # 4. Fetch 6-Month Trend Data (Grouped by Month)
    trend_query = (
        db.query(
            Item.category_id,
            func.strftime("%Y-%m", Receipt.purchase_date).label("month"),
            func.sum(ReceiptItem.price * ReceiptItem.quantity).label("total_spent"),
            func.sum(ReceiptItem.quantity).label("total_qty"),
        )
        .join(ReceiptItem, Item.id == ReceiptItem.item_id)
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .filter(Receipt.purchase_date >= six_months_ago)
        .group_by(Item.category_id, "month")
        .order_by(Item.category_id, "month")
        .all()
    )

    trend_lookup = {}
    months_list = sorted({r.month for r in trend_query})

    for row in trend_query:
        cat_id = row.category_id
        if cat_id not in trend_lookup:
            trend_lookup[cat_id] = dict.fromkeys(months_list, 0.0)

        # Trend is "Average Price Index" for the category
        # Or Total Spend? The user's image says "Avg price trend"
        avg_p = float(row.total_spent / row.total_qty) if row.total_qty > 0 else 0
        trend_lookup[cat_id][row.month] = round(avg_p, 2)

    # 5. Assemble Final Payload
    results = []

    for cat in categories:
        cat_stores = store_lookup.get(cat.id, [])
        if not cat_stores:
            continue  # Skip categories with no recent data

        # Find best price
        if cat_stores:
            min_price = min(s["avg_price"] for s in cat_stores)
            for s in cat_stores:
                if s["avg_price"] == min_price:
                    s["is_best_price"] = True

        # Sort stores by price (lowest first)
        cat_stores.sort(key=lambda x: x["avg_price"])

        # Prepare Trend Array
        cat_months = trend_lookup.get(cat.id, {})
        trend_data = [cat_months.get(m, 0.0) for m in months_list]

        results.append(
            {
                "id": cat.id,
                "name": cat.name,
                "item_count": db.query(Item).filter(Item.category_id == cat.id).count(),
                "stores": cat_stores,
                "trend": {
                    "labels": [datetime.strptime(m, "%Y-%m").strftime("%b") for m in months_list],
                    "data": trend_data,
                },
            }
        )

    return results


@router.get("/frequency-data")
def get_frequency_data(db: Session = Depends(get_db)):
    """
    Get data for the purchase frequency dot chart.
    Returns categories and the weeks they were purchased in.
    """
    from datetime import datetime, timedelta

    from app.models import Category

    # 1. Define time range (Past 6 months to keep it clean)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=180)

    # 2. Query: Categories and their purchase weeks
    results = (
        db.query(Item.category_id, func.strftime("%Y-%W", Receipt.purchase_date).label("week"))
        .join(ReceiptItem, Item.id == ReceiptItem.item_id)
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .filter(Receipt.purchase_date >= start_date)
        .group_by("week", Item.category_id)
        .order_by("week")
        .all()
    )

    # 3. Process Categories
    categories = db.query(Category).all()
    cat_map = {c.id: c.name for c in categories}
    cat_map[None] = "Other"

    # 4. Extract unique weeks for X-axis
    weeks = sorted({r.week for r in results if r.week})

    # 5. Build Datasets
    # We want a list of categories (Y-axis) and the weeks they appear in (Dots)
    active_cat_ids = sorted({r.category_id for r in results}, key=lambda x: cat_map.get(x, "zzz"))

    datasets = []
    for i, cat_id in enumerate(active_cat_ids):
        cat_name = cat_map.get(cat_id, "Other")
        # Find which weeks this category was purchased in
        purchase_weeks = [r.week for r in results if r.category_id == cat_id]

        # In a scatter chart, x is the week index, y is the category index
        points = []
        for w in purchase_weeks:
            if w in weeks:
                points.append({"x": weeks.index(w), "y": i})

        datasets.append(
            {
                "label": cat_name,
                "data": points,
                "pointRadius": 6,
                "pointHoverRadius": 8,
                "backgroundColor": "#3b82f6" if i % 2 == 0 else "#60a5fa",
            }
        )

    return {
        "labels": weeks,
        "categories": [cat_map.get(cid, "Other") for cid in active_cat_ids],
        "datasets": datasets,
    }


@router.get("/inflation")
def get_inflation_data(db: Session = Depends(get_db)):
    """
    Calculate the week-over-week price change (inflation index).
    Returns a list of weeks with their average price change percentage.
    """
    from collections import defaultdict
    from datetime import datetime

    # 1. Get all receipt items ordered by date
    from sqlalchemy import text

    query = text("""
    SELECT
        i.id,
        ri.price,
        r.purchase_date
    FROM receipt_items ri
    JOIN receipts r ON ri.receipt_id = r.id
    JOIN items i ON ri.item_id = i.id
    LEFT JOIN categories c ON i.category_id = c.id
    WHERE c.name IS NULL OR c.name NOT IN ('Excluded', 'Other')
    ORDER BY r.purchase_date ASC
    """)
    rows = db.execute(query).fetchall()

    # 2. Process changes
    last_prices = {}
    weekly_changes = defaultdict(list)

    for item_id, price, purchase_date in rows:
        try:
            # Handle string vs datetime object
            if isinstance(purchase_date, str):
                # Handle T or space separator
                clean_date = purchase_date.replace("T", " ").split(" ")[0]
                dt = datetime.strptime(clean_date, "%Y-%m-%d")
            else:
                dt = purchase_date

            week_str = dt.strftime("%Y-W%W")
        except (ValueError, TypeError, AttributeError):
            continue

        if item_id in last_prices:
            old_price = last_prices[item_id]
            if old_price > 0:
                change_pct = (price - old_price) / old_price
                weekly_changes[week_str].append(change_pct)

        last_prices[item_id] = price

    # 3. Format response
    sorted_weeks = sorted(weekly_changes.keys())
    results = []
    for week in sorted_weeks:
        changes = weekly_changes[week]
        avg_change = sum(changes) / len(changes) if changes else 0
        results.append({"week": week, "change": round(avg_change * 100, 1), "count": len(changes)})

    return results[-26:]  # Last 6 months of weeks


@router.get("/store-top-items")
def get_store_top_items(store: str, time_range: str = "year", db: Session = Depends(get_db)):
    """
    Get the top 5 most frequently purchased items for a specific store
    and their weekly price history.
    """
    from datetime import datetime, timedelta

    from sqlalchemy import func

    from app.models import Category, Item, Receipt, ReceiptItem, Store

    end_date = datetime.now()
    if time_range == "year":
        start_date = end_date - timedelta(days=365)
    elif time_range == "6m":
        start_date = end_date - timedelta(days=180)
    elif time_range == "ytd":
        start_date = datetime(end_date.year, 1, 1)
    else:
        start_date = None

    # 1. Find store
    store_obj = db.query(Store).filter(Store.name.ilike(f"%{store}%")).first()
    if not store_obj:
        return {"labels": [], "datasets": []}

    # 2. Get top 5 items
    top_items_query = (
        db.query(Item.id, Item.name, func.count(ReceiptItem.id).label("count"))
        .join(ReceiptItem, Item.id == ReceiptItem.item_id)
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .outerjoin(Category, Item.category_id == Category.id)
        .filter(Receipt.store_id == store_obj.id)
        .filter(
            or_(
                Category.name.is_(None),
                Category.name.notin_(["Excluded", "Other", "Fees & Taxes", "Non-Alcoholic Beer"]),
            )
        )
    )

    if start_date:
        top_items_query = top_items_query.filter(Receipt.purchase_date >= start_date)

    top_items = (
        top_items_query.group_by(Item.id, Item.name)
        .order_by(func.count(ReceiptItem.id).desc())
        .limit(5)
        .all()
    )

    if not top_items:
        return {"labels": [], "datasets": []}

    top_item_ids = [t.id for t in top_items]
    item_names = {t.id: t.name for t in top_items}

    # 3. Get history for these items
    history_query = (
        db.query(
            ReceiptItem.item_id,
            func.strftime("%Y-%W", Receipt.purchase_date).label("week"),
            func.avg(ReceiptItem.price).label("avg_price"),
        )
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .filter(Receipt.store_id == store_obj.id)
        .filter(ReceiptItem.item_id.in_(top_item_ids))
        .filter(Receipt.purchase_date.is_not(None))
    )

    if start_date:
        history_query = history_query.filter(Receipt.purchase_date >= start_date)

    history = history_query.group_by(ReceiptItem.item_id, "week").order_by("week").all()

    # 4. Extract unique weeks for X-axis
    weeks = sorted({r.week for r in history if r.week})

    # 5. Format datasets
    colors = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"]
    datasets = []

    for i, item_id in enumerate(top_item_ids):
        # Find which weeks this item was purchased
        data_points = []
        for w in weeks:
            # Find price for this week
            match = next(
                (r.avg_price for r in history if r.item_id == item_id and r.week == w), None
            )
            data_points.append(
                round(match, 2) if match else None
            )  # Null connects the line across gaps in Chart.js

        datasets.append(
            {
                "label": item_names[item_id][:30]
                + ("..." if len(item_names[item_id]) > 30 else ""),
                "data": data_points,
                "borderColor": colors[i % len(colors)],
                "backgroundColor": colors[i % len(colors)],
                "borderWidth": 2,
                "tension": 0.3,
                "spanGaps": True,  # Connect points across missing weeks
                "pointRadius": 4,
                "pointHoverRadius": 6,
            }
        )

    return {"store": store_obj.name, "labels": weeks, "datasets": datasets}


@router.get("/basket-composition")
def get_basket_composition(time_range: str = "30d", db: Session = Depends(get_db)):
    """
    Get Pie chart data for Basket Spend Composition (Direct relative spend percentages per category).
    Low data bootstrap chart.
    """
    from datetime import datetime, timedelta

    from sqlalchemy import func

    from app.models import Category, Item, Receipt, ReceiptItem

    end_date = datetime.now()
    if time_range == "30d":
        start_date = end_date - timedelta(days=30)
    elif time_range == "90d":
        start_date = end_date - timedelta(days=90)
    elif time_range == "6m":
        start_date = end_date - timedelta(days=180)
    elif time_range == "all":
        start_date = None
    else:
        start_date = end_date - timedelta(days=30)

    query = (
        db.query(
            Category.name, func.sum(ReceiptItem.price * ReceiptItem.quantity).label("total_spent")
        )
        .join(Item, ReceiptItem.item_id == Item.id)
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .outerjoin(Category, Item.category_id == Category.id)
    )

    if start_date:
        query = query.filter(Receipt.purchase_date >= start_date)

    results = (
        query.group_by(Category.name)
        .order_by(func.sum(ReceiptItem.price * ReceiptItem.quantity).desc())
        .all()
    )

    if not results:
        return {"labels": [], "datasets": []}

    labels = []
    data = []
    other_spent = 0.0

    for i, row in enumerate(results):
        cat_name = row.name if row.name else "Uncategorized"
        if i < 7:
            labels.append(cat_name)
            data.append(round(float(row.total_spent), 2))
        else:
            other_spent += float(row.total_spent)

    if other_spent > 0:
        labels.append("Other")
        data.append(round(other_spent, 2))

    colors = [
        "#3b82f6",
        "#10b981",
        "#f59e0b",
        "#ef4444",
        "#8b5cf6",
        "#ec4899",
        "#14b8a6",
        "#64748b",
    ]

    return {
        "labels": labels,
        "datasets": [
            {
                "data": data,
                "backgroundColor": colors[: len(labels)],
                "borderWidth": 0,
            }
        ],
    }


@router.get("/store-diff")
def get_store_diff(db: Session = Depends(get_db)):
    """
    Get Bar chart data for Identical Item Store-to-Store Diff.
    Price comparison of same-item unit cost across retailers.
    """
    from sqlalchemy import func

    from app.models import Item, Receipt, ReceiptItem, Store

    # Find items purchased at >1 store
    multi_store_items = (
        db.query(ReceiptItem.item_id)
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .group_by(ReceiptItem.item_id)
        .having(func.count(func.distinct(Receipt.store_id)) > 1)
        .scalar_subquery()
    )

    # Get top 5 most frequently purchased items from that list
    top_items = (
        db.query(Item.id, Item.name, func.count(ReceiptItem.id).label("freq"))
        .join(ReceiptItem, Item.id == ReceiptItem.item_id)
        .filter(Item.id.in_(multi_store_items))
        .group_by(Item.id, Item.name)
        .order_by(func.count(ReceiptItem.id).desc())
        .limit(5)
        .all()
    )

    if not top_items:
        return {"labels": [], "datasets": []}

    item_ids = [ti.id for ti in top_items]
    item_names = [ti.name for ti in top_items]

    # Get avg price per store for these items
    # Also need store names
    prices_query = (
        db.query(
            ReceiptItem.item_id,
            Store.name,
            func.avg(ReceiptItem.unit_price).label("avg_unit_price"),
        )
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .join(Store, Receipt.store_id == Store.id)
        .filter(ReceiptItem.item_id.in_(item_ids))
        .group_by(ReceiptItem.item_id, Store.name)
        .all()
    )

    store_names = sorted({r.name for r in prices_query})

    datasets = []
    colors = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6"]

    for i, s_name in enumerate(store_names):
        data = []
        for item_id in item_ids:
            # find price
            price = next(
                (
                    (float(r.avg_unit_price) if r.avg_unit_price is not None else 0.0)
                    for r in prices_query
                    if r.item_id == item_id and r.name == s_name
                ),
                0,
            )
            data.append(round(price, 2) if price else 0)

        # Only add dataset if store actually sells one of these top 5
        if any(d > 0 for d in data):
            datasets.append(
                {"label": s_name, "data": data, "backgroundColor": colors[i % len(colors)]}
            )

    return {
        "labels": [name[:20] + ("..." if len(name) > 20 else "") for name in item_names],
        "datasets": datasets,
    }


@router.get("/weekly-trajectory")
def get_weekly_trajectory(time_range: str = "6m", db: Session = Depends(get_db)):
    """
    Get Line chart data for Weekly Spend Trajectory.
    Clean aggregate spending trends over time.
    """
    from datetime import datetime, timedelta

    from sqlalchemy import func

    from app.models import Receipt

    end_date = datetime.now()
    if time_range == "3m":
        start_date = end_date - timedelta(days=90)
    elif time_range == "6m":
        start_date = end_date - timedelta(days=180)
    elif time_range == "year":
        start_date = end_date - timedelta(days=365)
    else:
        start_date = end_date - timedelta(days=180)

    query = db.query(
        func.strftime("%Y-%W", Receipt.purchase_date).label("week"),
        func.sum(Receipt.total_amount).label("total_amount"),
    )

    if start_date:
        query = query.filter(Receipt.purchase_date >= start_date)

    results = query.group_by("week").order_by("week").all()

    if not results:
        return {"labels": [], "datasets": []}

    labels = []
    data = []

    for row in results:
        if row.week:
            labels.append(row.week)
            data.append(round(float(row.total_amount), 2))

    return {
        "labels": labels,
        "datasets": [
            {
                "label": "Total Spend",
                "data": data,
                "borderColor": "#3b82f6",
                "backgroundColor": "rgba(59, 130, 246, 0.1)",
                "borderWidth": 3,
                "fill": True,
                "tension": 0.4,
            }
        ],
    }


@router.get("/fragment/all-charts")
def get_all_charts_fragment(
    time_range: str = "6m",
    usda_time_range: str = "6m",
    nutrient_type: str = "sugar",
    db: Session = Depends(get_db),
):
    import json

    # 1. Main weekly trends
    weekly = get_trends_data(time_range, db)

    # 2. Nutrition
    nutrition = get_nutrition_trends(time_range, nutrient_type, db)

    # 3. USDA
    usda = get_usda_product_types(usda_time_range, db)

    # 4. Stores
    store_fresh = get_store_top_items("Amazon Fresh", time_range, db)
    store_com = get_store_top_items("Amazon.com", time_range, db)
    store_wholefoods = get_store_top_items("Whole Foods", time_range, db)
    store_costco = get_store_top_items("Costco", time_range, db)

    # 5. Low-data
    basket = get_basket_composition(time_range, db)
    store_diff = get_store_diff(db)
    weekly_traj = get_weekly_trajectory(time_range, db)

    # 6. Tufte nutrition analysis
    calorie_profile = get_macronutrient_calories_data(time_range, db)
    nutrition_multiples = get_nutrition_multiples_data(time_range, db)
    nutrition_density = get_nutrition_density_data(time_range, db)
    nutrition_coverage = get_nutrition_coverage(time_range, db)
    _, nutrition_normalization = _get_nutrition_data(time_range, db)

    script = f"""
    <script>
        if (typeof updateAllCharts === 'function') {{
            updateAllCharts({{
                weekly: {json.dumps(weekly)},
                nutrition: {json.dumps(nutrition)},
                usda: {json.dumps(usda)},
                store_fresh: {json.dumps(store_fresh)},
                store_com: {json.dumps(store_com)},
                store_wholefoods: {json.dumps(store_wholefoods)},
                store_costco: {json.dumps(store_costco)},
                basket: {json.dumps(basket)},
                store_diff: {json.dumps(store_diff)},
                weekly_traj: {json.dumps(weekly_traj)},
                calorie_profile: {json.dumps(calorie_profile)},
                nutrition_multiples: {json.dumps(nutrition_multiples)},
                nutrition_density: {json.dumps(nutrition_density)},
                nutrition_coverage: {json.dumps(nutrition_coverage)},
                nutrition_normalization: {json.dumps(nutrition_normalization)}
            }});
        }}
    </script>
    """
    return HTMLResponse(content=script)
