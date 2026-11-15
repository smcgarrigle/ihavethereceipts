"""Hiding an item from restock predictions for a week, a month, or for good.

Two reasons a prediction is unwanted even when the arithmetic is right: the
item is only bought in season (egg nog, cranberries), or it was bought a few
times and is not wanted again. Neither can be read off the purchase history,
so a person says so.

A timed dismissal ends early when the item is bought again: the purchase
restarts the cycle, so the next reminder is a new one. A dismissal with no end
date survives a purchase, which is what keeps a once-a-year item from coming
back every year.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models.item import Item
from app.models.prediction_dismissal import PredictionDismissal

# What the dialog offers. A month is 30 days: the point is "not for a while",
# and a fixed length keeps "back on" dates predictable.
PERIODS: dict[str, timedelta | None] = {
    "week": timedelta(days=7),
    "month": timedelta(days=30),
    "forever": None,
}

PERIOD_LABELS = {"week": "1 week", "month": "1 month", "forever": "forever"}


def _now() -> datetime:
    """Naive UTC, matching how the DateTime columns are stored."""
    return datetime.now(UTC).replace(tzinfo=None)


def dismiss(db: Session, item_id: int, period: str) -> PredictionDismissal:
    """Hide an item for ``period``, replacing any earlier decision about it."""
    if period not in PERIODS:
        raise ValueError(f"period must be one of {tuple(PERIODS)}, not {period!r}")
    now = _now()
    length = PERIODS[period]
    row = db.query(PredictionDismissal).filter(PredictionDismissal.item_id == item_id).first()
    if row is None:
        row = PredictionDismissal(item_id=item_id)
        db.add(row)
    row.created_at = now
    row.until = now + length if length is not None else None
    db.commit()
    return row


def restore(db: Session, item_id: int) -> bool:
    """Bring an item back into predictions. False when it was not dismissed."""
    deleted = (
        db.query(PredictionDismissal)
        .filter(PredictionDismissal.item_id == item_id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return bool(deleted)


def is_active(
    dismissal: PredictionDismissal,
    last_purchased: date | None,
    now: datetime | None = None,
) -> bool:
    """Whether a dismissal still hides its item."""
    if dismissal.until is None:
        return True
    if (now or _now()) >= dismissal.until:
        return False
    # Bought again since: the cycle restarted, so the reminder it silenced is gone.
    return not (last_purchased is not None and last_purchased > dismissal.created_at.date())


def _last_purchases(cadences: list[dict[str, Any]]) -> dict[int, date]:
    """Last purchase date by item id, covering the variants pooled into an entry."""
    found: dict[int, date] = {}
    for entry in cadences:
        when = date.fromisoformat(entry["last_purchased"])
        found[entry["item_id"]] = when
        for variant in entry.get("variant_items") or []:
            found[variant["item_id"]] = when
    return found


def _active(db: Session, cadences: list[dict[str, Any]]) -> list[PredictionDismissal]:
    last = _last_purchases(cadences)
    now = _now()
    return [
        row
        for row in db.query(PredictionDismissal).all()
        if is_active(row, last.get(row.item_id), now)
    ]


def without_dismissed(db: Session, cadences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The cadence entries a person has not dismissed.

    An entry can pool several spellings of one product. Dismissing any of them
    hides the entry: which spelling leads the group changes as purchases
    accumulate, and the decision should not lapse when it does.
    """
    hidden = {row.item_id for row in _active(db, cadences)}
    if not hidden:
        return cadences
    return [
        entry
        for entry in cadences
        if entry["item_id"] not in hidden
        and not any(v["item_id"] in hidden for v in entry.get("variant_items") or [])
    ]


def list_dismissed(db: Session, cadences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Items currently hidden, soonest to return first and permanent ones last."""
    rows = _active(db, cadences)
    if not rows:
        return []
    names: dict[int, str] = {
        item_id: name or ""
        for item_id, name in db.query(Item.id, Item.name)
        .filter(Item.id.in_([row.item_id for row in rows]))
        .all()
    }
    listed: list[dict[str, Any]] = [
        {
            "item_id": row.item_id,
            "item_name": names[row.item_id],
            "until": row.until,
            "forever": row.until is None,
        }
        for row in sorted(
            (row for row in rows if row.item_id in names),
            key=lambda row: (
                row.until is None,
                row.until or datetime.max,
                names[row.item_id].lower(),
            ),
        )
    ]
    return listed


def repoint(db: Session, source_item_id: int, target_item_id: int) -> None:
    """Carry a dismissal across an item merge. Does not commit.

    The merged item is deleted, so its dismissal would otherwise point at
    nothing and the kept item would start being suggested again. A decision
    already recorded for the kept item wins.
    """
    source = (
        db.query(PredictionDismissal).filter(PredictionDismissal.item_id == source_item_id).first()
    )
    if source is None:
        return
    target = (
        db.query(PredictionDismissal).filter(PredictionDismissal.item_id == target_item_id).first()
    )
    if target is None:
        source.item_id = target_item_id
    else:
        db.delete(source)
