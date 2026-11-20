"""Prediction API router — exposes cadence data, shopping lists, and restock UI fragments."""

from collections import Counter

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.api.templates import templates
from app.database import get_db
from app.models.item import Item
from app.services import prediction_dismissals
from app.services.predictions import (
    get_item_cadences,
    get_prediction_stats,
    get_shopping_list,
)

router = APIRouter()


@router.get("/cadences")
def list_cadences(db: Session = Depends(get_db)):
    """Full cadence list for all eligible items (3+ purchases)."""
    cadences = get_item_cadences(db)
    return JSONResponse(content=cadences)


@router.get("/shopping-list")
def shopping_list(db: Session = Depends(get_db)):
    """Filtered urgent items only — designed for AI agent consumption."""
    items = get_shopping_list(db)
    return JSONResponse(content=items)


@router.get("/stats")
def prediction_stats(db: Session = Depends(get_db)):
    """Summary statistics for the prediction engine."""
    stats = get_prediction_stats(db)
    return JSONResponse(content=stats)


@router.get("/restock-table", response_class=HTMLResponse)
def restock_table_fragment(request: Request, db: Session = Depends(get_db)):
    """HTMX fragment — renders the restock table rows for the /restock page."""
    cadences = get_item_cadences(db)

    # Filter to non-stale items that are overdue, high, or medium urgency
    actionable = [
        c for c in cadences if c["urgency"] in ("overdue", "high", "medium") and not c["stale"]
    ]

    # Collect the 3 most common stores across actionable items
    top_stores = [
        store
        for store, _ in Counter(
            sp["store"] for c in actionable for sp in c["store_prices"]
        ).most_common(3)
    ]

    return templates.TemplateResponse(
        request,
        "fragments/restock_table.html",
        {
            "items": actionable,
            "stores": top_stores,
        },
    )


@router.get("/optimized-list", response_class=HTMLResponse)
def optimized_list_fragment(request: Request, db: Session = Depends(get_db)):
    """HTMX fragment — renders the optimized shopping list grouped by store."""
    cadences = get_item_cadences(db)

    # Filter to non-stale items that are overdue or high urgency
    actionable = [c for c in cadences if c["urgency"] in ("overdue", "high") and not c["stale"]]

    # Group by the absolute best store for each item
    # Since store_prices is already sorted by best price, index 0 is the best store
    store_groups: dict[str, list] = {}
    for item in actionable:
        best_store = "Unknown"
        if item["store_prices"]:
            best_store = item["store_prices"][0]["store"]

        if best_store not in store_groups:
            store_groups[best_store] = []
        store_groups[best_store].append(item)

    # Sort stores by number of items (descending) so the biggest trip is first
    sorted_store_groups = dict(
        sorted(store_groups.items(), key=lambda item: len(item[1]), reverse=True)
    )

    return templates.TemplateResponse(
        request,
        "fragments/optimized_list.html",
        {
            "store_groups": sorted_store_groups,
        },
    )


# ---------------------------------------------------------------------------
# Dismissing an item from predictions
#
# Each action returns the dismissed-items panel, plus an out-of-band notice
# with the way back, and fires ``restock-changed`` so the page reloads the list
# and the counts. CSRF rides on the htmx:configRequest listener in base.html.
# ---------------------------------------------------------------------------


def _dismissed_panel(
    request: Request,
    db: Session,
    notice: dict | None = None,
) -> HTMLResponse:
    dismissed = prediction_dismissals.list_dismissed(
        db, get_item_cadences(db, include_dismissed=True)
    )
    response = templates.TemplateResponse(
        request,
        "fragments/restock_dismissed.html",
        {"dismissed": dismissed, "notice": notice},
    )
    if notice is not None:
        response.headers["HX-Trigger"] = "restock-changed"
    return response


def _item_or_404(db: Session, item_id: int) -> Item:
    item = db.query(Item).filter(Item.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.get("/dismissed", response_class=HTMLResponse)
def dismissed_fragment(request: Request, db: Session = Depends(get_db)):
    """HTMX fragment: the items currently hidden from predictions."""
    return _dismissed_panel(request, db)


@router.post("/dismiss/{item_id}", response_class=HTMLResponse)
def dismiss_item(
    item_id: int,
    request: Request,
    period: str = Form(...),
    db: Session = Depends(get_db),
):
    """Hide an item from predictions for a week, a month, or for good."""
    if period not in prediction_dismissals.PERIODS:
        raise HTTPException(status_code=422, detail=f"Unknown period: {period}")
    item = _item_or_404(db, item_id)
    prediction_dismissals.dismiss(db, item_id, period)
    return _dismissed_panel(
        request,
        db,
        notice={
            "kind": "dismissed",
            "item_id": item_id,
            "item_name": item.name,
            "period": prediction_dismissals.PERIOD_LABELS[period],
            "forever": period == "forever",
        },
    )


@router.post("/dismiss/{item_id}/restore", response_class=HTMLResponse)
def restore_item(item_id: int, request: Request, db: Session = Depends(get_db)):
    """Bring a dismissed item back into predictions."""
    item = _item_or_404(db, item_id)
    prediction_dismissals.restore(db, item_id)
    return _dismissed_panel(
        request,
        db,
        notice={"kind": "restored", "item_id": item_id, "item_name": item.name},
    )
