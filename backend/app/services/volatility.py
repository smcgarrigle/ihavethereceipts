from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session, joinedload

from app.models import Receipt, ReceiptItem
from app.services.spend import comparable_price_series


def get_volatile_items(
    db: Session, threshold_pct: float = 0.15, days: int = 30
) -> list[dict[str, Any]]:
    """Find items with a significant price shift in the last N days compared to their history.

    Fetches all purchases, groups them by item, standardizes their price basis,
    and compares the average price in the recent window vs the historical average.
    """
    cutoff_date = datetime.now() - timedelta(days=days)

    # Fetch all relevant receipt items in a single query to avoid N+1
    receipt_items = (
        db.query(ReceiptItem)
        .join(Receipt)
        .filter(Receipt.purchase_date.isnot(None))
        .options(
            joinedload(ReceiptItem.item), joinedload(ReceiptItem.receipt).joinedload(Receipt.store)
        )
        .order_by(Receipt.purchase_date.desc())
        .all()
    )

    from collections import defaultdict

    item_map = defaultdict(list)
    for ri in receipt_items:
        if ri.item:
            item_map[ri.item].append(ri)

    volatile_items = []

    for item, lines in item_map.items():
        basis, series = comparable_price_series(lines)
        if not series:
            continue

        recent_prices = []
        historical_prices = []

        for ri, price in series:
            p_date = ri.receipt.purchase_date
            if isinstance(p_date, str):
                p_date = datetime.fromisoformat(p_date[:10])
            if not isinstance(p_date, datetime):
                p_date = datetime.combine(p_date, datetime.min.time())

            if p_date >= cutoff_date:
                recent_prices.append(price)
            else:
                historical_prices.append(price)

        # We need both recent and historical data to measure a shift
        if not recent_prices or not historical_prices:
            continue

        recent_avg = sum(recent_prices) / len(recent_prices)
        historical_avg = sum(historical_prices) / len(historical_prices)

        if historical_avg == 0:
            continue

        shift_pct = (recent_avg - historical_avg) / historical_avg

        if abs(shift_pct) >= threshold_pct:
            volatile_items.append(
                {
                    "item_id": item.id,
                    "item_name": item.name,
                    "basis": basis,
                    "recent_avg": round(recent_avg, 2),
                    "historical_avg": round(historical_avg, 2),
                    "shift_pct": round(shift_pct * 100, 1),
                    "trend": "up" if shift_pct > 0 else "down",
                    "recent_count": len(recent_prices),
                    "historical_count": len(historical_prices),
                }
            )

    # Sort by largest absolute shift descending
    volatile_items.sort(key=lambda x: abs(float(str(x["shift_pct"]))), reverse=True)
    return volatile_items
