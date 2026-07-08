"""
Receipt X-Ray — Intelligence API
Serves data for the Receipt X-Ray dashboard, which decodes
the hidden stories inside grocery receipt data.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Item, Receipt, ReceiptItem, Store

logger = logging.getLogger(__name__)
from app.api.analytics import _get_analytics_exclusions  # noqa: E402

router = APIRouter()


@router.get("/receipt-xray")
def receipt_xray_data(db: Session = Depends(get_db)):
    """
    Single endpoint that computes all 5 visualizations for the Receipt X-Ray page.
    Returns a JSON object with keys for each chart.
    """
    exclusions = _get_analytics_exclusions(db)

    # ── Shared Queries ─────────────────────────────────────────────────
    six_months_ago = datetime.now() - timedelta(days=180)

    receipts = (
        db.query(Receipt)
        .options(
            joinedload(Receipt.store),
            joinedload(Receipt.items).joinedload(ReceiptItem.item).joinedload(Item.category),
        )
        .filter(Receipt.status == "completed", Receipt.purchase_date.isnot(None))
        .order_by(Receipt.purchase_date.asc())
        .all()
    )

    recent_receipts = [r for r in receipts if r.purchase_date and r.purchase_date >= six_months_ago]

    # Pre-calculate valid receipt totals
    valid_receipt_totals = {}
    for r in receipts:
        valid_total = 0.0
        for ri in r.items:
            cat_name = ri.item.category.name if ri.item and ri.item.category else "Uncategorized"
            if any(ex in cat_name.lower() for ex in exclusions):
                continue
            if ri.price:
                valid_total += ri.price
        valid_receipt_totals[r.id] = valid_total

    # ── 1. PRICE VOLATILITY RADAR ──────────────────────────────────────
    # Which items swing the most in price? Reveals store pricing games.
    item_prices: dict[str, list[float]] = defaultdict(list)
    for r in receipts:
        for ri in r.items:
            cat_name = ri.item.category.name if ri.item and ri.item.category else "Uncategorized"
            if any(ex in cat_name.lower() for ex in exclusions):
                continue
            if ri.item and ri.price and ri.price > 0:
                item_prices[ri.item.name].append(ri.price)

    volatility_data = []
    for name, prices in item_prices.items():
        if len(prices) >= 3:  # Need at least 3 data points
            avg = sum(prices) / len(prices)
            min_p = min(prices)
            max_p = max(prices)
            spread = max_p - min_p
            spread_pct = (spread / avg * 100) if avg > 0 else 0
            volatility_data.append(
                {
                    "name": name,
                    "avg": round(avg, 2),
                    "min": round(min_p, 2),
                    "max": round(max_p, 2),
                    "spread": round(spread, 2),
                    "spread_pct": round(spread_pct, 1),
                    "count": len(prices),
                }
            )

    volatility_data.sort(key=lambda x: x["spread_pct"], reverse=True)
    chart_1 = volatility_data[:15]

    # ── 2. STORE DNA FINGERPRINT ───────────────────────────────────────
    # What does each store's "basket signature" look like?
    store_categories: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    store_totals: dict[str, float] = defaultdict(float)

    for r in recent_receipts:
        store_name = r.store.name if r.store else "Unknown"
        for ri in r.items:
            cat_name = ri.item.category.name if ri.item and ri.item.category else "Uncategorized"
            if any(ex in cat_name.lower() for ex in exclusions):
                continue
            if ri.item and ri.price:
                store_categories[store_name][cat_name] += ri.price
                store_totals[store_name] += ri.price

    chart_2 = []
    for store_name, cats in store_categories.items():
        if store_totals[store_name] < 20:  # Skip stores with minimal data
            continue
        breakdown = []
        for cat, spend in sorted(cats.items(), key=lambda x: x[1], reverse=True):
            pct = (
                round(spend / store_totals[store_name] * 100, 1)
                if store_totals[store_name] > 0
                else 0
            )
            breakdown.append({"category": cat, "spend": round(spend, 2), "pct": pct})
        chart_2.append(
            {
                "store": store_name,
                "total": round(store_totals[store_name], 2),
                "breakdown": breakdown[:8],
            }
        )

    chart_2.sort(key=lambda x: x["total"], reverse=True)

    # ── 3. THE PHANTOM ITEMS ───────────────────────────────────────────
    # Items you buy constantly but never think about. The "autopilot basket."
    item_frequency: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "total_spend": 0.0, "category": "Other", "stores": set()}
    )

    for r in receipts:
        store_name = r.store.name if r.store else "Unknown"
        for ri in r.items:
            cat_name = ri.item.category.name if ri.item and ri.item.category else "Uncategorized"
            if any(ex in cat_name.lower() for ex in exclusions):
                continue
            if ri.item and ri.price:
                entry = item_frequency[ri.item.name]
                entry["count"] += 1
                entry["total_spend"] += ri.price
                entry["category"] = cat_name
                entry["stores"].add(store_name)

    chart_3 = []
    for name, data in item_frequency.items():
        if data["count"] >= 3:
            chart_3.append(
                {
                    "name": name,
                    "count": data["count"],
                    "total_spend": round(data["total_spend"], 2),
                    "avg_price": round(data["total_spend"] / data["count"], 2),
                    "category": data["category"],
                    "stores": len(data["stores"]),
                }
            )
    chart_3.sort(key=lambda x: x["count"], reverse=True)
    chart_3 = chart_3[:20]

    # ── 4. SHOPPING RHYTHM ─────────────────────────────────────────────
    # Day-of-week and hour heatmap: when do you actually shop?
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    day_counts = [0] * 7
    day_spend = [0.0] * 7
    month_data: dict[str, dict] = defaultdict(lambda: {"trips": 0, "spend": 0.0})

    for r in receipts:
        if r.purchase_date:
            valid_total = valid_receipt_totals.get(r.id, 0)
            dow = r.purchase_date.weekday()
            day_counts[dow] += 1
            day_spend[dow] += valid_total

            month_key = r.purchase_date.strftime("%Y-%m")
            month_data[month_key]["trips"] += 1
            month_data[month_key]["spend"] += valid_total

    chart_4 = {
        "days": [
            {
                "name": day_names[i],
                "trips": day_counts[i],
                "spend": round(day_spend[i], 2),
                "avg": round(day_spend[i] / day_counts[i], 2) if day_counts[i] > 0 else 0,
            }
            for i in range(7)
        ],
        "months": [
            {
                "month": k,
                "trips": v["trips"],
                "spend": round(v["spend"], 2),
                "avg": round(v["spend"] / v["trips"], 2) if v["trips"] > 0 else 0,
            }
            for k, v in sorted(month_data.items())
        ],
    }

    # ── 5. RECEIPT COMPLEXITY SCORE ────────────────────────────────────
    # How "complex" is each receipt? Unique items, categories, total.
    # Reveals whether you're a "quick run" or "weekly haul" shopper.
    receipt_complexity = []
    for r in recent_receipts:
        if not r.items:
            continue
        categories_seen = set()
        item_count = 0
        for ri in r.items:
            cat_name = ri.item.category.name if ri.item and ri.item.category else "Uncategorized"
            if any(ex in cat_name.lower() for ex in exclusions):
                continue
            item_count += 1
            if ri.item and ri.item.category:
                categories_seen.add(cat_name)

        if item_count > 0:
            valid_total = valid_receipt_totals.get(r.id, 0)
            receipt_complexity.append(
                {
                    "id": r.id,
                    "date": r.purchase_date.strftime("%b %d") if r.purchase_date else "?",
                    "store": r.store.name if r.store else "Unknown",
                    "items": item_count,
                    "categories": len(categories_seen),
                    "total": round(valid_total, 2),
                    "avg_item_price": round(valid_total / item_count, 2),
                }
            )

    # Sort by date (most recent first)
    receipt_complexity.reverse()
    chart_5 = receipt_complexity[:30]

    # ── Summary Stats ──────────────────────────────────────────────────
    total_receipts = len(receipts)
    total_items_tracked = db.query(Item).count()
    total_stores = db.query(Store).count()
    total_spend = sum(valid_receipt_totals.values())
    avg_basket = round(total_spend / total_receipts, 2) if total_receipts > 0 else 0

    return {
        "summary": {
            "total_receipts": total_receipts,
            "total_items": total_items_tracked,
            "total_stores": total_stores,
            "total_spend": round(total_spend, 2),
            "avg_basket": avg_basket,
        },
        "price_volatility": chart_1,
        "store_dna": chart_2,
        "phantom_items": chart_3,
        "shopping_rhythm": chart_4,
        "receipt_complexity": chart_5,
    }
