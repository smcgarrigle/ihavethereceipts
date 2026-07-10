import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Receipt, Store

router = APIRouter()
logger = logging.getLogger(__name__)

# Upload directory
UPLOAD_DIR = Path(__file__).parent.parent.parent.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/upload")
def bulk_upload_receipts(files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    """
    Handle multiple receipt uploads and queue them for processing.
    """
    # 1. Get/Create Unknown Store
    store = db.query(Store).filter(Store.name == "Unknown Store").first()
    if not store:
        store = Store(name="Unknown Store")
        db.add(store)
        db.commit()
        db.refresh(store)

    results = []

    for file in files:
        # Validate file type
        allowed_types = ["image/jpeg", "image/jpg", "image/png", "application/pdf"]
        if file.content_type not in allowed_types:
            results.append({"filename": file.filename, "status": "error", "error": "Invalid type"})
            continue

        # Generate unique filename
        file_ext = Path(file.filename).suffix
        unique_filename = f"{uuid.uuid4()}{file_ext}"
        file_path = UPLOAD_DIR / unique_filename

        try:
            # Save file
            with file_path.open("wb") as buffer:
                import shutil

                shutil.copyfileobj(file.file, buffer)

            # Create receipt with pending status
            receipt = Receipt(
                store_id=store.id,
                image_path=str(file_path),
                total_amount=0.0,
                purchase_date=None,  # Will be set by OCR
                status="pending",
                notes=f"Bulk upload: {file.filename}",
                ocr_data=json.dumps({"items": [], "store_name": "Queued...", "total_amount": 0.0}),
            )
            db.add(receipt)
            db.commit()  # Commit individually to ensure partial success works
            results.append({"filename": file.filename, "status": "queued", "id": receipt.id})
        except Exception as e:
            db.rollback()  # Rollback if session is polluted
            logger.error(f"Error processing upload for {file.filename}: {e}")
            results.append({"filename": file.filename, "status": "error", "error": str(e)})

    return {"results": results}


@router.post("/clear-history")
def clear_bulk_history(db: Session = Depends(get_db)):
    """
    Clear completed/failed items from the bulk loader UI by stripping the 'Bulk upload:' prefix.
    """
    receipts = (
        db.query(Receipt)
        .filter(Receipt.notes.like("Bulk upload:%"), Receipt.status.in_(["completed", "failed"]))
        .all()
    )

    for r in receipts:
        r.notes = None

    db.commit()
    return {"status": "ok", "cleared": len(receipts)}


@router.get("/status", response_class=HTMLResponse)
def get_bulk_queue_status(db: Session = Depends(get_db)):
    """
    Return HTML fragment with stats for the bulk loader header.
    """
    import time

    from app.services.bulk_processor import bulk_processor

    stats = db.query(Receipt.status, func.count(Receipt.id)).group_by(Receipt.status).all()

    status_map = dict(stats)
    pending = status_map.get("pending", 0) + status_map.get("processing", 0)

    # Check if the queue is paused
    is_paused = time.time() < bulk_processor.pause_until
    if is_paused:
        pause_remaining = int(bulk_processor.pause_until - time.time())
        if pause_remaining < 60:
            pause_text = f"{pause_remaining}s"
        else:
            pause_text = f"{round(pause_remaining / 60)}m"

        return f"""
            <div class="text-center px-4 border-r border-gray-700">
                <p class="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-1">Queue Size</p>
                <p class="text-2xl font-black text-white">{pending}</p>
            </div>
            <div class="text-center px-4">
                <p class="text-[10px] font-bold text-yellow-500 uppercase tracking-widest mb-1">Queue Paused</p>
                <p class="text-2xl font-black text-yellow-400">Retry in {pause_text}</p>
            </div>
        """

    # Calculate ETR (approx 10s per item including cooldown)
    etr_seconds = pending * 10
    if etr_seconds < 60:
        etr_text = f"{etr_seconds}s"
    elif etr_seconds < 3600:
        etr_text = f"{round(etr_seconds / 60)}m"
    else:
        etr_text = f"{etr_seconds / 3600:.1f}h"

    return f"""
        <div class="text-center px-4 border-r border-gray-700">
            <p class="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-1">Queue Size</p>
            <p class="text-2xl font-black text-white">{pending}</p>
        </div>
        <div class="text-center px-4">
            <p class="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-1">Estimated Time</p>
            <p class="text-2xl font-black text-blue-400">{etr_text if pending > 0 else "0s"}</p>
        </div>
    """


@router.get("/active-items", response_class=HTMLResponse)
def get_active_queue_items(db: Session = Depends(get_db)):
    """
    Get the HTML list of receipts for the bulk UI with status bars.
    """
    # Get all pending or processing, plus the last 10 completed/failed
    # Filter for receipts that have "Bulk upload:" in notes to keep the list relevant to this tool
    query = db.query(Receipt).filter(Receipt.notes.like("Bulk upload:%"))

    pending_items = (
        query.filter(Receipt.status.in_(["pending", "processing"]))
        .order_by(Receipt.created_at.asc())
        .all()
    )
    recent_items = (
        query.filter(Receipt.status.in_(["completed", "failed"]))
        .order_by(Receipt.created_at.desc())
        .limit(15)
        .all()
    )

    items = pending_items + recent_items

    if not items:
        return """
        <div class="p-12 text-center text-gray-500">
            <p class="font-medium italic">No bulk uploads detected yet. Start by dropping some files.</p>
        </div>
        """

    html = ""
    for r in items:
        filename = r.notes.replace("Bulk upload: ", "") if r.notes else f"Receipt #{r.id}"

        # Determine status bar color and label
        ocr_data = json.loads(r.ocr_data) if r.ocr_data else {}
        is_duplicate = "duplicate_warning" in ocr_data

        if r.status == "completed":
            if is_duplicate:
                bar_color = "bg-yellow-500"
                status_label = "Possible Duplicate"
                status_text = "text-yellow-400"
                status_bg = "bg-yellow-500/10"
            else:
                bar_color = "bg-green-500"
                status_label = "Ingested"
                status_text = "text-green-400"
                status_bg = "bg-green-500/10"
        elif r.status == "processing":
            bar_color = "bg-orange-500 animate-pulse"
            status_label = "Ingesting..."
            status_text = "text-orange-400"
            status_bg = "bg-orange-500/10"
        elif r.status == "failed":
            bar_color = "bg-red-600"
            status_label = "Failed"
            status_text = "text-red-400"
            status_bg = "bg-red-500/10"
        else:  # pending
            bar_color = "bg-gray-600"
            status_label = "Waiting"
            status_text = "text-gray-400"
            status_bg = "bg-gray-500/10"

        html += f"""
        <div class="p-4 flex items-center justify-between hover:bg-white/5 transition">
            <div class="flex items-center space-x-4 flex-1">
                <!-- Status Bar (Adjacent to name) -->
                <div class="w-1.5 h-10 rounded-full {bar_color} shrink-0"></div>

                <div class="min-w-0">
                    <p class="text-sm font-bold text-white truncate">{filename}</p>
                    <div class="flex items-center mt-0.5 space-x-2">
                        <span class="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider {status_bg} {status_text}">{status_label}</span>
                        <span class="text-[10px] text-gray-600">ID: {r.id}</span>
                    </div>
                </div>
            </div>

            <div class="flex items-center space-x-4">
                {f'<span class="text-xs text-red-500/80 max-w-xs truncate font-medium">{r.error_message}</span>' if r.status == "failed" else ""}

                <div class="text-right">
                    <p class="text-[10px] font-bold text-gray-500 mb-1">{r.created_at.strftime("%H:%M:%S")}</p>
                    {'''<a href="/receipts/''' + str(r.id) + '''/review" class="text-[10px] font-black text-blue-400 hover:text-blue-300 uppercase tracking-widest no-underline">Review</a>''' if r.status == "completed" else ""}
                </div>
            </div>
        </div>
        """
    return html
