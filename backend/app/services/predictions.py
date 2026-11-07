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

# Only the most recent N purchase intervals feed the cadence average. Items
# with little history use everything they have; items with long history adapt
# to habit changes instead of being anchored by months-old intervals.
MAX_CADENCE_INTERVALS = 8

# Regularity bands on the coefficient of variation (std dev / mean interval).
# Below REGULAR_CV the cycle is dependable; above ERRATIC_CV the average
# describes nothing real.
REGULAR_CV = 0.5
ERRATIC_CV = 1.0

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


def invalidate_cadence_cache() -> None:
    """Clear the cached cadence computation after item merges or receipt saves."""
    _cadence_cache["data"] = None
    _cadence_cache["expires_at"] = 0.0


def _get_excluded_categories(db: Session) -> set[str]:
    """Fetch prediction-scoped exclusion patterns from the DB, always retaining defaults."""
    rules = db.query(ExclusionRule).filter(ExclusionRule.scope == "predictions").all()
    if rules:
        return _DEFAULT_EXCLUDED_CATEGORIES | {r.pattern for r in rules}
    return _DEFAULT_EXCLUDED_CATEGORIES


def _is_prediction_excluded(
    excluded_patterns: list[str], category_name: str, item_name: str = ""
) -> bool:
    cat_lower = category_name.lower()
    item_lower = item_name.lower()
    return any(pat in cat_lower or (item_lower and pat in item_lower) for pat in excluded_patterns)


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
    excluded_cats = _get_excluded_categories(db)
    all_rules = (
        db.query(ExclusionRule).filter(ExclusionRule.scope.in_(("predictions", "analytics"))).all()
    )
    excluded_patterns = [c.lower() for c in excluded_cats] + [
        r.pattern.lower() for r in all_rules if r.pattern
    ]

    # Respect user-dismissed duplicate pairs so ignored items are never pooled
    from app.models.item import ItemMatchIgnore
    from app.services.item_matcher import canonical_item_key

    ignored_pairs = {
        tuple(sorted([r.item_id_1, r.item_id_2])) for r in db.query(ItemMatchIgnore).all()
    }

    # Filter out excluded items first, then group unmerged canonical variants
    eligible_entries: list[tuple[int, dict[str, Any], str, str]] = []
    for item_id, data in item_data.items():
        item = data["item"]
        category_name = item.category.name if item.category else "Uncategorized"
        if category_name in excluded_cats or _is_prediction_excluded(
            excluded_patterns, category_name, item.name or ""
        ):
            continue
        canon_key = canonical_item_key(item.name or "")
        eligible_entries.append((item_id, data, category_name, canon_key))

    grouped_entries: list[dict[str, Any]] = []
    consumed_ids: set[int] = set()

    # Sort so items with the most purchases (then most recent purchase, then lowest id) lead groups
    eligible_entries.sort(
        key=lambda e: (
            len(e[1]["dates"]),
            max(e[1]["dates"]) if e[1]["dates"] else date.min,
            -e[0],
        ),
        reverse=True,
    )

    for item_id, data, category_name, canon_key in eligible_entries:
        if item_id in consumed_ids:
            continue
        consumed_ids.add(item_id)

        pooled_dates = set(data["dates"])
        pooled_store_prices: dict[str, list[tuple[float, date]]] = {
            s: list(plist) for s, plist in data["store_prices"].items()
        }
        variant_items: list[dict[str, Any]] = []

        if len(canon_key) >= 4:
            for other_id, other_data, other_cat, other_key in eligible_entries:
                if other_id in consumed_ids or other_key != canon_key:
                    continue
                if (
                    category_name != other_cat
                    and category_name != "Uncategorized"
                    and other_cat != "Uncategorized"
                ):
                    continue
                pair = tuple(sorted([item_id, other_id]))
                if pair in ignored_pairs:
                    continue

                consumed_ids.add(other_id)
                pooled_dates.update(other_data["dates"])
                for s_name, plist in other_data["store_prices"].items():
                    pooled_store_prices.setdefault(s_name, []).extend(plist)
                other_item = other_data["item"]
                variant_items.append(
                    {
                        "item_id": other_id,
                        "item_name": other_item.name,
                        "purchase_count": len(other_data["dates"]),
                    }
                )

        grouped_entries.append(
            {
                "item_id": item_id,
                "item": data["item"],
                "category_name": category_name,
                "dates": pooled_dates,
                "store_prices": pooled_store_prices,
                "variant_items": variant_items,
            }
        )

    for group in grouped_entries:
        item_id = group["item_id"]
        item = group["item"]
        category_name = group["category_name"]
        sorted_dates = sorted(group["dates"])
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

        # Trailing window: recent behavior describes the current habit better
        # than the full archive once enough history has accumulated.
        intervals = intervals[-MAX_CADENCE_INTERVALS:]

        # Median, not mean: interval spread is huge (CV ~1.3 across real data),
        # so a single bulk-buy gap drags a mean well off the habit.
        avg_interval = statistics.median(intervals)
        std_interval = statistics.stdev(intervals) if len(intervals) >= 2 else 0.0

        # Coefficient of variation (std dev / mean) — spread relative to the
        # item's own cycle, so weekly and yearly items compare on one scale.
        interval_mean = statistics.mean(intervals)
        cv = (std_interval / interval_mean) if interval_mean > 0 else 0.0
        if cv < REGULAR_CV:
            regularity = "regular"
        elif cv < ERRATIC_CV:
            regularity = "loose"
        else:
            regularity = "erratic"

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
        for store_name, price_list in group["store_prices"].items():
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

        results.append(
            {
                "item_id": item_id,
                "item_name": item.name,
                "category": category_name,
                "purchase_count": len(sorted_dates),
                "avg_interval": round(avg_interval, 1),
                "std_interval": round(std_interval, 1),
                "cv": round(cv, 2),
                "regularity": regularity,
                "last_purchased": last_purchased.isoformat(),
                "predicted_exhaustion": predicted_exhaustion.isoformat(),
                "confidence_window": confidence_window,
                "days_until": days_until,
                "urgency": urgency,
                "stale": is_stale,
                "store_prices": store_prices[:3],  # Top 3 stores by best price
                "variant_items": group["variant_items"],
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
