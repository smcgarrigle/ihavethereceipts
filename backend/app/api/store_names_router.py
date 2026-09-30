"""Moving past lines when a store's printed text comes to mean a different item.

A review save that changes a store name reports it with ``relink_suggestions``.
These routes let the review page preview the past lines that would move, then
move exactly those. Purchase history is rewritten, so nothing moves without a
preview first; moving them back is the same call with the items swapped.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Item, Receipt, Store
from app.services import store_names

router = APIRouter()


def _check(db: Session, store_id: int, *item_ids: int) -> None:
    if db.get(Store, store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    for item_id in item_ids:
        if db.get(Item, item_id) is None:
            raise HTTPException(status_code=404, detail=f"Item {item_id} not found")


@router.get("/relink/preview")
def preview_relink(
    store_id: int,
    text_key: str,
    from_item_id: int,
    to_item_id: int,
    exclude_receipt_id: int | None = None,
    db: Session = Depends(get_db),
):
    """The past lines a move would change, oldest purchase first."""
    _check(db, store_id, from_item_id, to_item_id)
    lines = store_names.past_lines(
        db, store_id, text_key, from_item_id, exclude_receipt_id=exclude_receipt_id
    )
    dates = {
        r.id: (r.purchase_date.date().isoformat() if r.purchase_date else None)
        for r in db.query(Receipt).filter(Receipt.id.in_({line.receipt_id for line in lines}))
    }
    return {
        "lines": [
            {
                "line_id": line.id,
                "receipt_id": line.receipt_id,
                "purchase_date": dates.get(line.receipt_id),
                "price": line.price,
                "quantity": line.quantity,
            }
            for line in lines
        ]
    }


class RelinkRequest(BaseModel):
    store_id: int
    text_key: str
    from_item_id: int
    to_item_id: int
    line_ids: list[int]


@router.post("/relink")
def relink(request: RelinkRequest, db: Session = Depends(get_db)):
    """Move the previewed lines that still qualify to the new item."""
    _check(db, request.store_id, request.from_item_id, request.to_item_id)
    moved = store_names.move_lines(
        db,
        request.store_id,
        request.text_key,
        request.from_item_id,
        request.to_item_id,
        request.line_ids,
    )
    db.commit()
    return {"success": True, "moved": moved}
