import logging
import threading
import time
from pathlib import Path

from app.database import SessionLocal
from app.models import Receipt
from app.services.receipt_claim import claim_receipt

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Setup dedicated file logging for bulk processing
log_file = Path(__file__).parent.parent.parent.parent / "data" / "bulk.log"
file_handler = logging.FileHandler(log_file)
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logger.addHandler(file_handler)


class BulkProcessor:
    """
    Singleton service that manages a background thread to process
    pending receipts sequentially with a delay to respect API rate limits.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.stop_requested = False
        self.worker_thread = None
        self.cooldown_seconds = 5  # Safe delay between successful Gemini calls
        self.pause_until = 0  # Timestamp until which the queue is paused
        self._initialized = True
        logger.info("✓ BulkProcessor service initialized")

    def start(self):
        """Start the background worker thread if not already running."""
        with self._lock:
            if self.worker_thread and self.worker_thread.is_alive():
                return

            self.stop_requested = False
            self.worker_thread = threading.Thread(target=self._run_worker, daemon=True)
            self.worker_thread.start()
            logger.info("🚀 BulkProcessor worker thread started")

    def stop(self):
        """Request the worker thread to stop."""
        self.stop_requested = True
        logger.info("⏹ BulkProcessor stop requested")

    def _claim_next_pending(self, db) -> Receipt | None:
        """Return the oldest pending receipt this worker successfully claimed.

        An interactive upload or the folder watcher may be processing the same
        row: the claim is what decides, so a lost race yields None and the
        worker leaves the receipt alone.
        """
        receipt: Receipt | None = (
            db.query(Receipt)
            .filter(Receipt.status == "pending")
            .filter(Receipt.image_path.isnot(None))
            .order_by(Receipt.created_at.asc())
            .first()
        )
        if receipt is None:
            return None

        if not claim_receipt(db, receipt.id):
            logger.info(f"[BulkProcessor] Receipt {receipt.id} claimed elsewhere; skipping")
            return None

        return receipt

    def _run_worker(self):
        """Main loop that polls for pending receipts."""
        while not self.stop_requested:
            # Check if we are currently paused
            if time.time() < self.pause_until:
                remaining = int(self.pause_until - time.time())
                if remaining % 60 == 0 or remaining < 10:  # Log occasionally
                    logger.info(f"[BulkProcessor] Queue paused. Resuming in {remaining}s...")
                time.sleep(min(remaining, 5))
                continue

            db = SessionLocal()
            try:
                # 0. Maintenance: Reset any items stuck in "processing" for too long (> 1 hour)
                from datetime import datetime, timedelta

                stuck_time = datetime.now() - timedelta(hours=1)
                stuck_items = (
                    db.query(Receipt)
                    .filter(Receipt.status == "processing")
                    .filter(Receipt.created_at < stuck_time)
                ).all()
                for stuck in stuck_items:
                    logger.warning(f"[BulkProcessor] Resetting stuck receipt {stuck.id} to failed")
                    stuck.status = "failed"
                    stuck.error_message = "Processing timeout (stuck in processing)"
                if stuck_items:
                    db.commit()

                # 1. Claim the oldest pending receipt (only image-based ones)
                receipt = self._claim_next_pending(db)

                if receipt:
                    logger.info(f"[BulkProcessor] Starting processing for receipt {receipt.id}...")

                    # Process the receipt using the existing task logic
                    try:
                        from app.services.ocr import process_receipt_task

                        process_receipt_task(receipt.id, receipt.image_path, claimed=True)
                    except Exception as e:
                        logger.error(
                            f"[BulkProcessor] Fatal error in task call for receipt {receipt.id}: {e}"
                        )
                        db.query(Receipt).filter(Receipt.id == receipt.id).update(
                            {"status": "failed", "error_message": f"Worker error: {str(e)}"}
                        )
                        db.commit()

                    # Refresh receipt from DB to check status after task
                    db.refresh(receipt)

                    # 2. Check for rate limit failures to trigger backoff
                    if receipt.status == "failed" and receipt.error_message:
                        err = receipt.error_message.lower()
                        if "429" in err or "quota" in err or "resource_exhausted" in err:
                            # Reset to pending so it can be retried automatically
                            receipt.status = "pending"
                            receipt.error_message = None  # Clear error to show it's waiting again
                            db.commit()

                            # Determine pause duration (Default 1 hour for safety)
                            pause_duration = 3600

                            # Try to parse "retry in X.Xs" from Gemini message
                            import re

                            match = re.search(r"retry in ([\d\.]+)s", err)
                            if match:
                                pause_duration = float(match.group(1)) + 10  # Add safety buffer

                            self.pause_until = time.time() + pause_duration
                            logger.warning(
                                f"[BulkProcessor] ⚠️ Rate limit hit. Pausing queue for {int(pause_duration)}s. Receipt {receipt.id} reset to pending."
                            )
                            db.close()
                            continue  # Skip cooldown and re-loop (will hit the pause check at top)

                    logger.info(
                        f"[BulkProcessor] Finished processing attempt for receipt {receipt.id}"
                    )
                    # Wait for cooldown to respect rate limits
                    time.sleep(self.cooldown_seconds)
                else:
                    # No pending receipts, sleep for a bit before checking again
                    time.sleep(2)

            except Exception as e:
                logger.error(f"[BulkProcessor] Worker loop error: {e}")
                time.sleep(5)
            finally:
                db.close()


# Global instance
bulk_processor = BulkProcessor()
