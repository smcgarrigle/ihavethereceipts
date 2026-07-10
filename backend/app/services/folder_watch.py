"""Folder-watch ingester — auto-import receipts dropped into a watch folder.

Drop a PDF/JPG/PNG into the inbox (default: data/inbox next to data/uploads)
and it is picked up, moved into uploads, given a Receipt row, and queued
through the normal OCR pipeline — the same flow as a manual upload, minus the
browser. Files must be size-stable across two polls before ingestion, so
partially-copied files are never consumed.

Configuration (env):
  FOLDER_WATCH=0          disable entirely (default: enabled)
  WATCH_FOLDER=<path>     override the inbox location
"""

import json
import logging
import os
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("app.folder_watch")

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
MAX_SIZE_BYTES = 10 * 1024 * 1024  # match the upload endpoint's limit
POLL_SECONDS = 10

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
UPLOAD_DIR = _PROJECT_ROOT / "data" / "uploads"


def _inbox_dir() -> Path:
    override = os.getenv("WATCH_FOLDER")
    return Path(override) if override else _PROJECT_ROOT / "data" / "inbox"


class FolderWatcher:
    """Background thread polling the inbox for new receipt files."""

    def __init__(self, session_factory=None):
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._pending_sizes: dict[str, int] = {}  # path -> size seen last poll
        self._session_factory = session_factory  # injectable for tests

    def start(self) -> None:
        if os.getenv("FOLDER_WATCH", "1") != "1":
            logger.info("Folder watch disabled (FOLDER_WATCH != 1)")
            return
        if self._thread and self._thread.is_alive():
            return
        inbox = _inbox_dir()
        inbox.mkdir(parents=True, exist_ok=True)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="folder-watch", daemon=True)
        self._thread.start()
        logger.info(f"📂 Folder watch started: {inbox}")

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=POLL_SECONDS + 5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.scan_once()
            except Exception:
                logger.exception("Folder watch scan failed")
            self._stop.wait(POLL_SECONDS)

    def scan_once(self) -> list[int]:
        """One inbox pass. Returns receipt ids created (for tests)."""
        inbox = _inbox_dir()
        if not inbox.is_dir():
            return []

        created: list[int] = []
        seen_now: dict[str, int] = {}
        for path in sorted(inbox.iterdir()):
            if not path.is_file() or path.suffix.lower() not in ALLOWED_EXTENSIONS:
                continue
            size = path.stat().st_size
            seen_now[str(path)] = size

            # Ingest only when the size matches the previous poll (stable file)
            if self._pending_sizes.get(str(path)) != size:
                continue
            if size == 0:
                continue
            if size > MAX_SIZE_BYTES:
                logger.warning(f"Folder watch: {path.name} exceeds 10MB, moving to inbox/rejected")
                rejected = inbox / "rejected"
                rejected.mkdir(exist_ok=True)
                shutil.move(str(path), rejected / path.name)
                continue

            receipt_id = self._ingest(path)
            if receipt_id:
                created.append(receipt_id)

        self._pending_sizes = seen_now
        return created

    def _ingest(self, path: Path) -> int | None:
        """Move a stable file into uploads and run it through the OCR pipeline."""
        from app.database import SessionLocal
        from app.models import Receipt, Store
        from app.services.ocr import process_receipt_task

        session_factory = self._session_factory or SessionLocal
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        unique_filename = f"{uuid.uuid4()}{path.suffix.lower()}"
        dest = UPLOAD_DIR / unique_filename
        shutil.move(str(path), dest)

        db = session_factory()
        try:
            store = db.query(Store).filter(Store.name == "Unknown Store").first()
            if not store:
                store = Store(name="Unknown Store")
                db.add(store)
                db.commit()
                db.refresh(store)

            receipt = Receipt(
                store_id=store.id,
                image_path=str(dest),
                total_amount=0.0,
                purchase_date=datetime.now(),
                status="pending",
                ocr_data=json.dumps(
                    {"items": [], "store_name": "Processing...", "total_amount": 0.0}
                ),
                notes=f"folder_watch:{path.name}",
            )
            db.add(receipt)
            db.commit()
            db.refresh(receipt)
            receipt_id = receipt.id
        finally:
            db.close()

        logger.info(f"📂 Ingested {path.name} as receipt {receipt_id}")
        try:
            process_receipt_task(receipt_id, str(dest))
        except Exception:
            logger.exception(f"Folder watch: OCR failed for receipt {receipt_id}")
        return receipt_id


folder_watcher = FolderWatcher()
