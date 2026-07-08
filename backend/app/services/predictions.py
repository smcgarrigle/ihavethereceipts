"""Purchase Cadence Engine — predicts reorder timing from historical purchase data.

Analyzes receipt_items joined through receipts to compute per-item purchase
intervals, predicted exhaustion dates, urgency levels, and per-store pricing.
"""

import os
import statistics
import time
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session, joinedload

from app.models.exclusion import ExclusionRule
from app.models.item import Item
from app.models.receipt import Receipt, ReceiptItem

# Minimum number of distinct purchase dates required to compute a cadence
MIN_PURCHASES = 3

# Items not purchased in this many days are marked stale
STALE_THRESHOLD_DAYS = 180

# Fallback exclusion set if the DB table is empty
_DEFAULT_EXCLUDED_CATEGORIES = {
    "Excluded",
    "Other",
    "Non-Alcoholic Beer",
    "Fees & Taxes",
    "CRV (tax)",
}

# Simple TTL cache so multiple endpoints hitting the same request don't re-query
_cadence_cache: dict[str, Any] = {"data": None, "expires_at": 0.0}
_CACHE_TTL_SECONDS = 30


def _get_excluded_categories(db: Session) -> set[str]:
    """Fetch prediction-scoped exclusion patterns from the DB."""
    rules = db.query(ExclusionRule).filter(ExclusionRule.scope == "predictions").all()
    if rules:
        return {r.pattern for r in rules}
    return _DEFAULT_EXCLUDED_CATEGORIES


def get_item_cadences(db: Session) -> list[dict[str, Any]]:
    """Compute purchase cadences for all items with >= MIN_PURCHASES purchases.

    Results are cached for _CACHE_TTL_SECONDS to avoid redundant full-table
    scans when multiple endpoints (stats, restock-table, optimized-list) are
    called in rapid succession.

    Returns a list of dicts, each containing:
        item_id, item_name, category, purchase_count, avg_interval,
        std_interval, last_purchased, predicted_exhaustion,
        confidence_window, urgency, stale, store_prices
    """
    now = time.monotonic()
    is_testing = os.getenv("TESTING") == "1"
    if not is_testing and _cadence_cache["data"] is not None and now < _cadence_cache["expires_at"]:
        from typing import cast

        return cast(list[dict[str, Any]], _cadence_cache["data"])

    today = date.today()

    # Batch query: get all receipt_items with their receipt dates and store info
    # Using joinedload to avoid N+1
    all_ri = (
        db.query(ReceiptItem)
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .filter(Receipt.purchase_date.isnot(None))
        .options(
            joinedload(ReceiptItem.item).joinedload(Item.category),
            joinedload(ReceiptItem.receipt).joinedload(Receipt.store),
        )
        .all()
    )

    # Group purchase dates and store prices by item_id
    item_data: dict[int, dict[str, Any]] = {}
    for ri in all_ri:
        if not ri.item or not ri.item_id or not ri.receipt or not ri.receipt.purchase_date:
            continue

        item_id = ri.item_id
        purchase_dt = ri.receipt.purchase_date
        purchase_date = purchase_dt.date() if isinstance(purchase_dt, datetime) else purchase_dt

        if item_id not in item_data:
            item_data[item_id] = {
                "item": ri.item,
                "dates": set(),
                "store_prices": {},  # store_name -> list of (price, date)
            }

        item_data[item_id]["dates"].add(purchase_date)

        # Track per-store pricing (use the line-item effective price)
        store_name = ri.receipt.store.name if ri.receipt.store else "Unknown"
        effective_price = float(ri.price or 0.0) * float(ri.quantity or 1.0)
        if store_name not in item_data[item_id]["store_prices"]:
            item_data[item_id]["store_prices"][store_name] = []
        item_data[item_id]["store_prices"][store_name].append((effective_price, purchase_date))

    results = []
    for item_id, data in item_data.items():
        item = data["item"]
        category_name = item.category.name if item.category else "Uncategorized"

        if category_name in _get_excluded_categories(db):
            continue

        sorted_dates = sorted(data["dates"])
        if len(sorted_dates) < MIN_PURCHASES:
            continue

        # Compute intervals between consecutive purchases
        intervals = [
            (sorted_dates[i + 1] - sorted_dates[i]).days for i in range(len(sorted_dates) - 1)
        ]

        # Filter out zero-day intervals (same-day duplicate purchases)
        intervals = [iv for iv in intervals if iv > 0]
        if not intervals:
            continue

        avg_interval = statistics.mean(intervals)
        std_interval = statistics.stdev(intervals) if len(intervals) >= 2 else 0.0

        last_purchased = sorted_dates[-1]
        predicted_exhaustion = last_purchased + timedelta(days=avg_interval)
        confidence_window = max(2, round(std_interval / 2))

        # Determine urgency
        days_until = (predicted_exhaustion - today).days
        is_stale = (today - last_purchased).days > STALE_THRESHOLD_DAYS

        if days_until < -confidence_window:
            urgency = "overdue"
        elif days_until <= confidence_window:
            urgency = "high"
        elif days_until <= 7:
            urgency = "medium"
        else:
            urgency = "low"

        # Build store price summary (most recent price per store, sorted best first)
        store_prices = []
        for store_name, price_list in data["store_prices"].items():
            # Use most recent price for this store
            most_recent = max(price_list, key=lambda x: x[1])
            store_prices.append(
                {
                    "store": store_name,
                    "price": round(most_recent[0], 2),
                    "date": most_recent[1].isoformat(),
                }
            )
        store_prices.sort(key=lambda x: x["price"])

        item = data["item"]
        results.append(
            {
                "item_id": item_id,
                "item_name": item.name,
                "category": category_name,
                "purchase_count": len(sorted_dates),
                "avg_interval": round(avg_interval, 1),
                "std_interval": round(std_interval, 1),
                "last_purchased": last_purchased.isoformat(),
                "predicted_exhaustion": predicted_exhaustion.isoformat(),
                "confidence_window": confidence_window,
                "days_until": days_until,
                "urgency": urgency,
                "stale": is_stale,
                "store_prices": store_prices[:3],  # Top 3 stores by best price
            }
        )

    # Sort by predicted exhaustion (most urgent first)
    results.sort(key=lambda x: x["predicted_exhaustion"])

    if not is_testing:
        _cadence_cache["data"] = results
        _cadence_cache["expires_at"] = time.monotonic() + _CACHE_TTL_SECONDS

    return results


def get_shopping_list(db: Session) -> list[dict[str, Any]]:
    """Return only urgent (high/overdue), non-stale items — agent-friendly."""
    cadences = get_item_cadences(db)
    return [c for c in cadences if c["urgency"] in ("high", "overdue") and not c["stale"]]


def get_prediction_stats(db: Session) -> dict[str, Any]:
    """Summary statistics for the prediction engine."""
    cadences = get_item_cadences(db)
    if not cadences:
        return {
            "total_tracked": 0,
            "urgent_count": 0,
            "overdue_count": 0,
            "stale_count": 0,
            "avg_cadence_days": 0,
        }

    return {
        "total_tracked": len(cadences),
        "urgent_count": sum(
            1 for c in cadences if c["urgency"] in ("high", "overdue") and not c["stale"]
        ),
        "overdue_count": sum(1 for c in cadences if c["urgency"] == "overdue"),
        "stale_count": sum(1 for c in cadences if c["stale"]),
        "avg_cadence_days": round(statistics.mean(c["avg_interval"] for c in cadences), 1),
    }
