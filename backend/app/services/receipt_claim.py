"""Atomic claim on a receipt row, so only one code path processes it.

The upload endpoint (via BackgroundTasks), the bulk worker and the folder
watcher can all reach process_receipt_task for the same receipt. The claim is a
single conditional UPDATE, so exactly one of them wins the pending -> processing
transition and the losers back off.
"""

import logging

from sqlalchemy.orm import Session

from app.models import Receipt

logger = logging.getLogger(__name__)


def claim_receipt(db: Session, receipt_id: int, *, force: bool = False) -> bool:
    """Move a receipt from pending to processing, returning True if we own it.

    One UPDATE ... WHERE status = 'pending': the loser of a race updates zero
    rows and must not process the receipt. force=True claims from any status,
    for the manual reprocess scripts that deliberately re-run a finished row.
    """
    query = db.query(Receipt).filter(Receipt.id == receipt_id)
    if not force:
        query = query.filter(Receipt.status == "pending")

    claimed = query.update({"status": "processing"}, synchronize_session=False)
    db.commit()
    return claimed == 1
