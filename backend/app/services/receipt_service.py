from sqlalchemy.orm import Session

from app.models import Receipt


def check_potential_duplicate(db: Session, receipt: Receipt) -> dict | None:
    """
    Check if a receipt is a potential duplicate of an existing one.
    Returns a warning dict if duplicate found, None otherwise.
    """
    if not receipt.store_id or not receipt.purchase_date:
        return None

    # Look for receipts from same store
    query = db.query(Receipt).filter(Receipt.store_id == receipt.store_id, Receipt.id != receipt.id)

    potential_dupes = query.all()

    for other in potential_dupes:
        if not other.purchase_date:
            continue

        # Check Order Number (strongest signal)
        if (
            receipt.order_number
            and other.order_number
            and receipt.order_number == other.order_number
        ):
            return {
                "type": "duplicate",
                "id": other.id,
                "message": f"Exact order number match found (ID: {other.id})",
                "confidence": "high",
            }

        # Check Total (if both are non-zero)
        same_total = False
        if receipt.total_amount and other.total_amount:
            if abs(receipt.total_amount - other.total_amount) < 0.01:
                same_total = True

        # Check Date/Time
        time_diff = abs((receipt.purchase_date - other.purchase_date).total_seconds())
        same_time = time_diff < 3600  # 1 hour

        # Duplicate Criteria:
        # Same Store AND Same Total AND (Same Time OR same day)
        if same_total:
            if same_time:
                return {
                    "type": "duplicate",
                    "id": other.id,
                    "message": f"Exact match found (ID: {other.id})",
                    "confidence": "high",
                }
            elif time_diff < 86400:  # Same day
                return {
                    "type": "duplicate",
                    "id": other.id,
                    "message": f"Same store/amount on same day (ID: {other.id})",
                    "confidence": "medium",
                }

    return None
