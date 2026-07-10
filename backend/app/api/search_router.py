"""Global search API — returns item search results as an HTML fragment (dropdown)
and a full-page result set for the /search route.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.api.templates import templates
from app.database import get_db
from app.models.item import Item
from app.models.receipt import Receipt, ReceiptItem
from app.models.store import Store

router = APIRouter()

# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _search_items(q: str, db: Session, limit: int = 12) -> list[dict]:
    """Return items matching *q* enriched with their most recent purchase info."""
    items = (
        db.query(Item)
        .filter(
            or_(
                Item.name.ilike(f"{q}%"),
                Item.name.ilike(f"% {q}%"),
                Item.name.ilike(f"%{q}%"),
            )
        )
        .options(joinedload(Item.category))
        .limit(limit)
        .all()
    )

    results = []
    for item in items:
        # Grab the single most-recent purchase for this item
        latest_ri = (
            db.query(ReceiptItem)
            .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
            .join(Store, Receipt.store_id == Store.id)
            .filter(ReceiptItem.item_id == item.id)
            .filter(Receipt.purchase_date.isnot(None))
            .order_by(Receipt.purchase_date.desc())
            .options(joinedload(ReceiptItem.receipt).joinedload(Receipt.store))
            .first()
        )

        last_store = None
        last_date = None
        last_price = None
        if latest_ri and latest_ri.receipt:
            last_store = latest_ri.receipt.store.name if latest_ri.receipt.store else None
            last_date = latest_ri.receipt.purchase_date
            last_price = latest_ri.price

        results.append(
            {
                "item": item,
                "last_store": last_store,
                "last_date": last_date,
                "last_price": last_price,
            }
        )

    return results


# ---------------------------------------------------------------------------
# Dropdown fragment (HTMX nav bar)
# ---------------------------------------------------------------------------


@router.get("/search", response_class=HTMLResponse)
def global_search(
    q: str = "",
    request: Request = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
):
    """Returns an HTML fragment of item search results for the nav bar dropdown."""
    q = q.strip()
    if len(q) < 2:
        return HTMLResponse("")

    results = _search_items(q, db, limit=8)

    return templates.TemplateResponse(
        "fragments/search_results.html",
        {
            "request": request,
            "results": results,
            "query": q,
        },
    )
