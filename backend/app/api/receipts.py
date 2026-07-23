"""Receipt lifecycle: upload, manual/produce creation, item edits, delete, reprocess.

The review-save flow lives in receipts_review.py and the HTMX fragments in
receipts_fragments.py; all three routers mount on the same /api/receipts prefix.
"""

import html
import json
import logging
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.receipts_fragments import get_receipt_card
from app.database import get_db
from app.models import Receipt, ReceiptItem, Store
from app.services.ocr import process_receipt_task, process_text_receipt_task

router = APIRouter()
logger = logging.getLogger(__name__)

# Upload directory
UPLOAD_DIR = Path(__file__).parent.parent.parent.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.get("/{receipt_id}/file")
def get_receipt_file(receipt_id: int, db: Session = Depends(get_db)):
    """Serve the original receipt file (image or PDF)"""
    receipt = db.query(Receipt).filter(Receipt.id == receipt_id).first()
    if not receipt or not receipt.image_path:
        raise HTTPException(status_code=404, detail="File not found")

    path = Path(receipt.image_path)

    # If it's just a filename, assume it's in UPLOAD_DIR
    if not path.is_absolute():
        path = UPLOAD_DIR / path.name

    if not path.exists():
        # Try one more fallback: maybe it's just the filename stored in image_path
        fallback_path = UPLOAD_DIR / Path(receipt.image_path).name
        if fallback_path.exists():
            path = fallback_path
        else:
            raise HTTPException(status_code=404, detail=f"File not found on disk: {path}")

    # Determine media type
    media_type = "application/octet-stream"
    ext = path.suffix.lower()
    if ext in [".jpg", ".jpeg"]:
        media_type = "image/jpeg"
    elif ext == ".png":
        media_type = "image/png"
    elif ext == ".pdf":
        media_type = "application/pdf"

    return FileResponse(str(path), media_type=media_type)


@router.post("/upload")
def upload_receipt(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a receipt image or PDF and process with OCR, then redirect to review"""

    # Validate file type
    allowed_types = ["image/jpeg", "image/jpg", "image/png", "application/pdf"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"File type {file.content_type} not allowed. Use JPG, PNG, or PDF.",
        )

    # Validate file size (10MB max)
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)

    if file_size > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large. Max 10MB.")

    # Generate unique filename
    file_ext = Path(file.filename).suffix
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = UPLOAD_DIR / unique_filename

    # Save file
    with file_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Get default store
    store = db.query(Store).filter(Store.name == "Unknown Store").first()
    if not store:
        store = Store(name="Unknown Store")
        db.add(store)
        db.commit()
        db.refresh(store)

    # Create receipt with pending status
    receipt = Receipt(
        store_id=store.id,
        image_path=str(file_path),
        total_amount=0.0,
        purchase_date=datetime.now(),
        status="pending",
        ocr_data=json.dumps({"items": [], "store_name": "Processing...", "total_amount": 0.0}),
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)

    # Process in background
    background_tasks.add_task(process_receipt_task, receipt.id, str(file_path))

    # Redirect to review page (which will handle polling)
    return HTMLResponse(f"""
        <div class="p-4 bg-blue-100 dark:bg-blue-900/30 border border-blue-400 dark:border-blue-700 text-blue-700 dark:text-blue-400 rounded-lg">
            <p class="font-semibold">✓ Upload Successful</p>
            <p class="text-sm mt-1">Receipt ID: {receipt.id}</p>
            <p class="text-sm">Processing in background...</p>
        </div>
        <script>
            window.location.href = '/receipts/{receipt.id}/review';
        </script>
    """)


class PasteReceiptRequest(BaseModel):
    text: str


@router.post("/paste")
def paste_receipt_text(
    request: PasteReceiptRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Create a receipt from pasted text and parse with AI in background."""

    raw_text = request.text.strip()
    if not raw_text or len(raw_text) < 20:
        raise HTTPException(
            status_code=400,
            detail="Receipt text is too short. Please paste the full receipt.",
        )

    if len(raw_text) > 50_000:
        raise HTTPException(
            status_code=400,
            detail="Text too long. Maximum 50,000 characters.",
        )

    # Get default store (will be updated by AI parsing)
    store = db.query(Store).filter(Store.name == "Unknown Store").first()
    if not store:
        store = Store(name="Unknown Store")
        db.add(store)
        db.commit()
        db.refresh(store)

    # Create receipt with pending status
    receipt = Receipt(
        store_id=store.id,
        image_path=None,
        total_amount=0.0,
        purchase_date=datetime.now(),
        status="pending",
        ocr_data=json.dumps(
            {"items": [], "store_name": "Processing...", "total_amount": 0.0, "text_paste": True}
        ),
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)

    # Process in background
    background_tasks.add_task(process_text_receipt_task, receipt.id, raw_text)

    return {
        "success": True,
        "receipt_id": receipt.id,
        "message": "Receipt text submitted for analysis",
    }


class ManualReceiptRequest(BaseModel):
    store_name: str
    purchase_date: str | None = None
    total_amount: float | None = 0.0
    notes: str | None = None


@router.post("/manual")
def create_manual_receipt(request: ManualReceiptRequest, db: Session = Depends(get_db)):
    """Create a receipt manually without an image"""

    # Normalize/Find/Create Store
    from app.services.store_utils import normalize_store_name

    store_name = normalize_store_name(request.store_name)

    store = db.query(Store).filter(Store.name == store_name).first()
    if not store:
        store = Store(name=store_name)
        db.add(store)
        db.commit()
        db.refresh(store)

    # Parse Date
    purchase_date = datetime.now()
    if request.purchase_date:
        try:
            purchase_date = datetime.strptime(request.purchase_date, "%Y-%m-%d")
        except ValueError:
            logger.warning(f"Failed to parse purchase date: {request.purchase_date}")
            pass  # Keep default if parse fails

    if purchase_date and purchase_date > datetime.now():
        raise HTTPException(status_code=400, detail="Purchase date cannot be in the future")

    # Create Receipt
    receipt = Receipt(
        store_id=store.id,
        image_path=None,  # Explicitly None
        total_amount=request.total_amount or 0.0,
        purchase_date=purchase_date,
        notes=request.notes,
        ocr_data=json.dumps(
            {
                "items": [],
                "store_name": store.name,
                "total_amount": request.total_amount or 0.0,
                "manual_entry": True,
            }
        ),
        status="completed",
    )

    db.add(receipt)
    db.commit()
    db.refresh(receipt)

    return {
        "success": True,
        "receipt_id": receipt.id,
        "message": "Manual receipt created",
    }


class ProduceItem(BaseModel):
    name: str
    weight: float
    price: float


class ProduceReceiptRequest(BaseModel):
    store_name: str
    purchase_date: str | None = None
    items: list[ProduceItem]


@router.post("/produce")
def create_produce_receipt(request: ProduceReceiptRequest, db: Session = Depends(get_db)):
    """Streamlined endpoint for bulk-adding produce hauls"""
    from app.models import Category, Item, ReceiptItem
    from app.services.item_matcher import get_best_match, get_store_item_ids
    from app.services.store_utils import normalize_store_name

    # 1. Store Setup
    store_name = normalize_store_name(request.store_name)
    store = db.query(Store).filter(Store.name == store_name).first()
    if not store:
        store = Store(name=store_name)
        db.add(store)
        db.commit()
        db.refresh(store)

    try:
        purchase_date = (
            datetime.strptime(request.purchase_date, "%Y-%m-%d")
            if request.purchase_date
            else datetime.now()
        )
    except ValueError:
        purchase_date = datetime.now()

    # 2. Receipt Creation
    receipt = Receipt(
        store_id=store.id,
        total_amount=sum(i.price for i in request.items),
        purchase_date=purchase_date,
        status="completed",
        ocr_data=json.dumps({"items": [], "store_name": store.name, "produce_mode": True}),
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)

    # 3. Item Processing
    all_items = db.query(Item).all()
    store_item_ids = get_store_item_ids(db, store.id)
    for p_item in request.items:
        norm_name = p_item.name.lower().strip()
        item = get_best_match(
            p_item.name, db, threshold=85, existing_items=all_items, store_item_ids=store_item_ids
        )

        if not item:
            # Auto-categorize as 'Produce' or find/create Produce category
            category = db.query(Category).filter(Category.name == "Produce").first()
            if not category:
                category = Category(name="Produce")
                db.add(category)
                db.commit()
                db.refresh(category)

            item = Item(name=p_item.name, normalized_name=norm_name, category_id=category.id)
            db.add(item)
            db.commit()
            db.refresh(item)
            all_items.append(item)

        # Save Receipt Item
        unit_price = p_item.price / p_item.weight if p_item.weight > 0 else p_item.price
        ri = ReceiptItem(
            receipt_id=receipt.id,
            item_id=item.id,
            quantity=1,  # Haul entries usually treat the whole weight as 1 unit
            price=unit_price,
            weight=p_item.weight,
            unit_type="lb",
            unit_price=unit_price,
            notes=json.dumps({"is_bulk": True, "source": "produce_mode"}),
        )
        db.add(ri)

    db.commit()
    return {"success": True, "receipt_id": receipt.id}


class UpdateReceiptItemRequest(BaseModel):
    quantity: float | None = None
    price: float | None = None
    notes: str | None = None


@router.put("/{receipt_id}/items/{item_id}")
def update_receipt_item(
    receipt_id: int,
    item_id: int,
    update: UpdateReceiptItemRequest,
    db: Session = Depends(get_db),
):
    """Update a receipt item"""

    from app.models import ReceiptItem

    receipt_item = (
        db.query(ReceiptItem)
        .filter(ReceiptItem.receipt_id == receipt_id, ReceiptItem.id == item_id)
        .first()
    )

    if not receipt_item:
        raise HTTPException(status_code=404, detail="Receipt item not found")

    # Update fields if provided
    if update.quantity is not None:
        receipt_item.quantity = update.quantity
    if update.price is not None:
        receipt_item.price = update.price
    if update.notes is not None:
        receipt_item.notes = update.notes

    db.commit()
    db.refresh(receipt_item)

    # Recalculate receipt total
    receipt = db.query(Receipt).filter(Receipt.id == receipt_id).first()
    total = sum(ri.price * ri.quantity for ri in receipt.items)
    receipt.total_amount = total
    db.commit()

    return {"success": True, "message": "Item updated"}


@router.delete("/{receipt_id}/items/{item_id}")
def delete_receipt_item(receipt_id: int, item_id: int, db: Session = Depends(get_db)):
    """Delete an item from a receipt"""

    from app.models import ReceiptItem

    receipt_item = (
        db.query(ReceiptItem)
        .filter(ReceiptItem.receipt_id == receipt_id, ReceiptItem.id == item_id)
        .first()
    )

    if not receipt_item:
        raise HTTPException(status_code=404, detail="Receipt item not found")

    db.delete(receipt_item)
    db.commit()

    # Recalculate receipt total
    receipt = db.query(Receipt).filter(Receipt.id == receipt_id).first()
    total = sum(ri.price * ri.quantity for ri in receipt.items)
    receipt.total_amount = total
    db.commit()

    return {"success": True, "message": "Item deleted"}


@router.delete("/{receipt_id}")
def delete_receipt(receipt_id: int, db: Session = Depends(get_db)):
    """Delete a receipt and all its items"""
    receipt = db.query(Receipt).filter(Receipt.id == receipt_id).first()
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    # Store info for a nice response message
    store_name = receipt.store.name if receipt.store else "Unknown Store"
    total = receipt.total_amount

    # Delete all items first
    db.query(ReceiptItem).filter(ReceiptItem.receipt_id == receipt_id).delete()
    db.delete(receipt)
    db.commit()

    # Return a status message for HTMX
    escaped_store_name = html.escape(store_name)
    return HTMLResponse(f"""
        <div class="p-4 bg-orange-100 dark:bg-orange-900/30 border-2 border-orange-500 dark:border-orange-700 text-orange-800 dark:text-orange-300 rounded-lg animate-pulse">
            <p class="font-semibold">🗑️ Receipt Deleted</p>
            <p class="text-sm mt-1">{escaped_store_name} - ${total:.2f}</p>
        </div>
    """)


@router.post("/{receipt_id}/reprocess")
def reprocess_receipt(
    receipt_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    """Re-trigger the OCR processing task for an existing receipt"""
    receipt = db.query(Receipt).filter(Receipt.id == receipt_id).first()
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    if not receipt.image_path or not os.path.exists(receipt.image_path):
        raise HTTPException(status_code=400, detail="Receipt has no image to process")

    # Reset status and trigger background task
    receipt.status = "pending"
    db.commit()

    background_tasks.add_task(process_receipt_task, receipt.id, receipt.image_path)
    return {"status": "processing", "receipt_id": receipt_id}


@router.get("/{receipt_id}/status")
def get_receipt_status(receipt_id: int, db: Session = Depends(get_db)):
    """Get the processing status of a receipt"""
    receipt = db.query(Receipt).filter(Receipt.id == receipt_id).first()
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    return {
        "id": receipt.id,
        "status": receipt.status,
        "error_message": receipt.error_message if receipt.status == "failed" else None,
    }


@router.patch("/{receipt_id}")
def patch_receipt(
    request: Request,
    receipt_id: int,
    store_name: str | None = Form(None),
    purchase_date: str | None = Form(None),
    total_amount: float | None = Form(None),
    db: Session = Depends(get_db),
):
    """Update receipt metadata (store, date, total_amount)"""

    receipt = db.query(Receipt).filter(Receipt.id == receipt_id).first()
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    # Update Store
    if store_name:
        from app.services.store_utils import normalize_store_name

        store_name = normalize_store_name(store_name.strip())
        # Find existing store or create new one
        store = db.query(Store).filter(Store.name == store_name).first()
        if not store:
            store = Store(name=store_name)
            db.add(store)
            db.commit()
            db.refresh(store)

        receipt.store_id = store.id

    # Update Date
    if purchase_date:
        try:
            # Try parsing as full datetime first, then date
            if "T" in purchase_date:
                receipt.purchase_date = datetime.fromisoformat(purchase_date.replace("Z", "+00:00"))
            else:
                receipt.purchase_date = datetime.strptime(purchase_date, "%Y-%m-%d")
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail="Invalid date format. Use YYYY-MM-DD or ISO format.",
            ) from e

    if total_amount is not None:
        receipt.total_amount = total_amount

    db.commit()
    db.refresh(receipt)

    # If it's an HTMX request, return the updated card fragment
    if request.headers.get("HX-Request"):
        return get_receipt_card(receipt_id, db)

    return {"success": True, "message": "Receipt updated"}
