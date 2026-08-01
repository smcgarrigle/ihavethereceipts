"""Page routes — server-rendered HTML views.

Extracted from main.py so app wiring and page rendering live apart.
Fragment/JSON endpoints live in their own routers under /api.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from app.api.templates import templates
from app.database import get_db

logger = logging.getLogger("app.pages")
router = APIRouter()

BASE_DIR = Path(__file__).resolve().parents[2]


@router.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(BASE_DIR / "static" / "favicon.svg")


@router.get("/", response_class=HTMLResponse)
def root(request: Request, db: Session = Depends(get_db)):
    from sqlalchemy.orm import joinedload

    from app.models import Receipt, Store

    # Check if empty, and trigger onboarding demo data
    receipt_count = db.query(Receipt).count()
    if receipt_count == 0:
        from app.services.onboarding import populate_demo_data

        populate_demo_data(db)

    # Fetch all stores with their receipts
    stores = db.query(Store).outerjoin(Store.receipts).all()
    all_receipts = db.query(Receipt).options(joinedload(Receipt.items)).all()

    # Calculate Global Totals
    total_spent = sum(r.total_amount or 0 for r in all_receipts)
    total_savings = sum(r.discount_amount or 0 for r in all_receipts)
    for r in all_receipts:
        total_savings += sum(item.total_discount or 0 for item in r.items)

    savings_percent = (
        (total_savings / (total_spent + total_savings) * 100)
        if (total_spent + total_savings) > 0
        else 0
    )

    dashboard_data = []

    # Pre-group receipts by store_id to avoid O(n*m) loop (Fixed Audit #3.37)
    receipts_by_store = {}
    for r in all_receipts:
        if r.store_id not in receipts_by_store:
            receipts_by_store[r.store_id] = []
        receipts_by_store[r.store_id].append(r)

    for store in stores:
        # Get receipts for this store from our pre-built map
        store_receipts = receipts_by_store.get(store.id, [])
        store_receipts.sort(key=lambda x: x.purchase_date or datetime.min, reverse=True)

        # Calculate total
        store_total = sum(r.total_amount or 0 for r in store_receipts)

        # Only add valid stores with positive spending
        if store_total > 0:
            dashboard_data.append(
                {
                    "id": store.id,
                    "name": store.name,
                    "total_spent": store_total,
                    "receipts": store_receipts,
                }
            )

    # Sort stores by total spent (highest first)
    dashboard_data.sort(key=lambda x: x["total_spent"], reverse=True)

    # Onboarding details
    is_demo = any(r.notes == "DEMO_DATA" for r in all_receipts)
    has_gemini_key = bool(os.getenv("GEMINI_API_KEY"))

    return templates.TemplateResponse(
        request,
        "pages/dashboard.html",
        {
            "stores": dashboard_data,
            "total_spent": total_spent,
            "total_savings": total_savings,
            "savings_percent": round(savings_percent, 1),
            "is_demo": is_demo,
            "has_gemini_key": has_gemini_key,
        },
    )


@router.post("/api/onboarding/clear-demo")
def post_clear_demo(db: Session = Depends(get_db)):
    from app.services.onboarding import clear_demo_data

    success = clear_demo_data(db)
    if not success:
        from fastapi import HTTPException

        raise HTTPException(status_code=500, detail="Failed to clear demo data")
    return HTMLResponse(
        content="<script>window.location.reload();</script>", headers={"HX-Refresh": "true"}
    )


@router.get("/receipts", response_class=HTMLResponse)
def receipts_page(request: Request, db: Session = Depends(get_db)):
    import os

    from app.services.ocr import get_backend, get_daily_usage

    backend = get_backend()
    ocr_model_name = (
        os.getenv("OCR_MODEL", "llava:7b")
        if backend == "local"
        else os.getenv("GEMINI_MODEL_NAME", "gemini-flash")
    )
    from app.models import Receipt, Store

    # Get all stores that have receipts, normalized to avoid duplicates (e.g. iHerb vs Iherb)
    stores = db.query(Store).join(Receipt).distinct().all()
    # Use a set to deduplicate case-insensitively while preserving a "best" name
    store_map = {}
    for s in stores:
        normalized = s.name.lower().strip()
        if normalized not in store_map:
            store_map[normalized] = s.name

    sorted_stores = sorted(store_map.values())

    return templates.TemplateResponse(
        request,
        "pages/receipts.html",
        {
            "ocr_usage": get_daily_usage(),
            "ocr_model": ocr_model_name,
            "ocr_backend": get_backend(),
            "stores": sorted_stores,
        },
    )


@router.get("/receipts/bulk", response_class=HTMLResponse)
def bulk_upload_page(request: Request):
    """Dedicated page for mass-loading receipts"""
    return templates.TemplateResponse(
        request,
        "pages/bulk.html",
    )


@router.get("/receipts/{receipt_id}/review", response_class=HTMLResponse)
def review_receipt(request: Request, receipt_id: int, db: Session = Depends(get_db)):
    """Review page for receipt after OCR processing"""
    from fastapi import HTTPException

    from app.models import Category, Receipt

    receipt = db.query(Receipt).filter(Receipt.id == receipt_id).first()
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found")

    if receipt.status in ["pending", "processing"]:
        from app.core.config import settings
        from app.services.model_manager import model_manager

        cached = model_manager.get_cached_models()
        models_list = (
            cached.get("models", ["gemini-flash", "gemini-pro"])
            if cached
            else ["gemini-flash", "gemini-pro"]
        )
        models_json = json.dumps(models_list)
        models_json = json.dumps(models_list)
        backend_type = settings.OCR_BACKEND
        backend_url = settings.OCR_BACKEND_URL
        local_model = settings.OCR_MODEL

        return HTMLResponse(f"""
        <!DOCTYPE html>
        <html lang="en" class="h-full bg-gray-900">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Processing Receipt - Grocery Tracker</title>
            <link rel="stylesheet" href="/static/css/tailwind.css">
            <style>
                @keyframes blink {{
                    0%, 100% {{ opacity: 1; }}
                    50% {{ opacity: 0; }}
                }}
                .cursor-blink {{
                    animation: blink 1s step-end infinite;
                }}
                /* Scanline effect */
                .scanline {{
                    background: linear-gradient(to bottom, rgba(255,255,255,0), rgba(255,255,255,0) 50%, rgba(0,0,0,0.1) 50%, rgba(0,0,0,0.1));
                    background-size: 100% 4px;
                }}
                /* EQ Bar animation */
                @keyframes eq-fill {{
                    0% {{ width: 0%; }}
                    100% {{ width: 100%; }}
                }}
                .eq-bar {{
                    height: 15px;
                    width: 0%;
                    background: repeating-linear-gradient(
                        90deg,
                        #22c55e 0px,
                        #22c55e 6px,
                        transparent 6px,
                        transparent 10px
                    );
                    animation: eq-fill 20s linear forwards;
                }}
                /* Animated ellipsis */
                @keyframes loading-dots {{
                    0% {{ content: ''; }}
                    25% {{ content: '.'; }}
                    50% {{ content: '..'; }}
                    75% {{ content: '...'; }}
                    100% {{ content: ''; }}
                }}
                .dots::after {{
                    content: '';
                    animation: loading-dots 1.5s infinite;
                    display: inline-block;
                    text-align: left;
                    width: 1em; /* prevent layout shift */
                }}
            </style>
        </head>
        <body class="h-full flex flex-col items-center justify-center p-4 bg-gray-900">
            <div class="w-full max-w-2xl bg-black rounded border-2 border-gray-800 p-1 relative overflow-hidden shadow-[0_0_20px_rgba(34,197,94,0.15)]">
                <!-- Top Bar -->
                <div class="bg-gray-800 flex justify-between items-center px-3 py-1 mb-1 shadow-sm">
                    <span class="text-xs font-mono text-gray-400 tracking-wider">TERM // GROCERY_OCR</span>
                    <span class="text-[10px] font-mono text-green-500 animate-pulse">CONNECTING</span>
                </div>

                <!-- Terminal Window -->
                <div class="bg-black scanline relative h-80 sm:h-96 w-full p-4 overflow-hidden flex flex-col justify-end">
                    <div id="term-output" class="text-green-500 font-mono text-xs sm:text-sm tracking-wide leading-relaxed space-y-1 block max-h-full overflow-hidden transition-all break-words">
                    </div>
                </div>

                <!-- Bottom Bar -->
                <div class="bg-gray-800 px-3 py-1 pb-5 mt-1 flex justify-between text-gray-500 font-mono text-[10px] uppercase relative overflow-hidden">
                    <span class="relative z-10">RID: {receipt_id}</span>
                    <span class="relative z-10 flex gap-4">
                        <span>Extracting data<span class="dots"></span></span>
                        <span>AI Engine Active</span>
                    </span>
                    <div class="absolute bottom-0 left-0 eq-bar opacity-80"></div>
                </div>
            </div>

            <script>
                const term = document.getElementById('term-output');
                const receiptId = "{receipt_id}";
                const knownModels = {models_json};
                const ocrBackend = "{backend_type}";
                const backendUrl = "{backend_url}";
                const localModel = "{local_model}";

                // Animation Logic
                const sequence = [
                    "============== INITIALIZING VISION PIPELINE ==============",
                    "[INIT] Establishing secure link to OCR Gateway...",
                    "[INFO] Target payload Receipt ID: " + receiptId + " acquired.",
                    "[TASK] Serializing image bytes for transport... [████████] 100%",
                    " ",
                    "==== NEURAL INFERENCE ENGINE START ===="
                ];

                if (ocrBackend === "local") {{
                    let serverType = backendUrl.includes("11434") ? "Ollama daemon" : "LM Studio API";
                    sequence.push("Pinging local " + serverType + " at " + backendUrl + "...");
                    sequence.push("Handshake OK. Connection Latency: 0.2ms");
                    sequence.push("Requesting vision-language tensor allocation...");
                    sequence.push(" > PROBE: Found local weights for " + localModel);
                    sequence.push(" ");
                    sequence.push("Mounting parameters into VRAM: " + localModel);
                    sequence.push("[WARN] VRAM thermal limit approaching. Fan RPM: 4200");
                    sequence.push("Quantizing context window to 8-bit precision...");
                    sequence.push("Initiating neural extraction matrix...");
                }} else {{
                    sequence.push("Querying model registry for available AI engines...");
                    knownModels.forEach(m => {{
                        sequence.push(" > FOUND CLOUD MODEL: " + m);
                    }});
                    sequence.push(" ");
                    sequence.push("Selecting optimal routing engine: " + (knownModels[0] || 'auto'));
                    sequence.push("Validating Google Cloud IAM Bearer Tokens...");
                    sequence.push("Normalizing multi-modal vector embeddings...");
                    sequence.push("Transmitting matrix over HTTPS [██████████] 100%");
                    sequence.push("Executing semantic extraction protocol...");
                }}

                const randomEvents = [];
                if (ocrBackend === "local") {{
                    randomEvents.push("Allocating KV cache buffers... OK");
                    randomEvents.push("Generating tokens... 24.5 t/s");
                    randomEvents.push("Generating tokens... 38.2 t/s");
                    randomEvents.push("Scanning image topological anomalies...");
                    randomEvents.push("VRAM usage spike: 7.8GB / 8.0GB allocated");
                    randomEvents.push("Parsing semi-structured discount geometries...");
                    randomEvents.push("Generating tokens... 41.9 t/s");
                    randomEvents.push("Waiting on local LLM completion threshold...");
                }} else {{
                    randomEvents.push("Routing packet through US-Central-1a...");
                    randomEvents.push("Parsing JSON schema constraints...");
                    randomEvents.push("[WARN] 429 RESOURCE_EXHAUSTED. Free tier throttled.");
                    randomEvents.push("Engaging exponential backoff script. Retrying...");
                    randomEvents.push("[RETRY] Attempt 2 utilizing " + (knownModels[0] || 'auto') + "...");
                    randomEvents.push("Detecting line items via spatial mapping...");
                    randomEvents.push("Cross-referencing price indices...");
                    randomEvents.push("Awaiting final Google Cloud HTTP 200 OK...");
                }}
                randomEvents.push(null); // triggers polling loop print

                let lineIdx = 0;
                let eventIdx = 0;

                function writeLine(text) {{
                    const el = document.createElement('div');
                    el.innerHTML = text.replace(/ /g, '&nbsp;');

                    // Old blinker removal
                    const old = document.getElementById('blinker');
                    if(old) old.remove();

                    // Add text
                    term.appendChild(el);

                    // Add new blinker
                    const blinker = document.createElement('span');
                    blinker.className = 'cursor-blink';
                    blinker.innerText = '█';
                    blinker.id = 'blinker';
                    term.appendChild(blinker);
                }}

                function streamSequence() {{
                    if (lineIdx < sequence.length) {{
                        writeLine(sequence[lineIdx]);
                        lineIdx++;
                        setTimeout(streamSequence, Math.random() * 250 + 50);
                    }} else {{
                        setTimeout(streamEvents, 400);
                    }}
                }}

                function streamEvents() {{
                    if (eventIdx < randomEvents.length) {{
                        const ev = randomEvents[eventIdx];
                        if (ev === null) {{
                            startPolling();
                        }} else {{
                            writeLine(ev);
                            eventIdx++;
                            setTimeout(streamEvents, Math.random() * 800 + 400);
                        }}
                    }}
                }}

                function startPolling() {{
                    const pollInterval = setInterval(() => {{
                        fetch('/api/receipts/' + receiptId + '/status')
                            .then(res => res.json())
                            .then(data => {{
                                if (data.status === 'completed' || data.status === 'failed') {{
                                    clearInterval(pollInterval);
                                    writeLine(" ");
                                    if (data.status === 'completed') {{
                                        writeLine("==== JSON DATA EXTRACTED ====");
                                        writeLine("[SUCCESS] Routing to review matrix...");
                                    }} else {{
                                        writeLine("==== PROCESS FAILED ====");
                                        writeLine("[ERROR] " + (data.error_message || "OCR engine crashed."));
                                    }}

                                    setTimeout(() => {{
                                        window.location.reload();
                                    }}, 1500);
                                }} else {{
                                    // Add gibberish processing hex
                                    const oldBlinker = document.getElementById('blinker');
                                    if(oldBlinker) oldBlinker.remove();
                                    const gibberish = Array.from({{length: 4}}, () => Math.floor(Math.random()*16).toString(16)).join('');
                                    term.appendChild(document.createTextNode(' 0x'+gibberish));

                                    const newBlinker = document.createElement('span');
                                    newBlinker.className = 'cursor-blink';
                                    newBlinker.innerText = '█';
                                    newBlinker.id = 'blinker';
                                    term.appendChild(newBlinker);
                                }}
                            }})
                            .catch(e => console.error(e));
                    }}, 2000);
                }}

                // Boot delay
                setTimeout(streamSequence, 600);
            </script>
        </body>
        </html>
        """)

    # Handle Failed Status
    ocr_error = None
    if receipt.status == "failed":
        ocr_error = receipt.error_message or "Unknown error"
    # Get OCR data from receipt
    try:
        ocr_data = json.loads(receipt.ocr_data) if receipt.ocr_data else None
    except json.JSONDecodeError:
        ocr_data = None

    date_str = (
        receipt.purchase_date.strftime("%Y-%m-%d")
        if receipt.purchase_date
        else datetime.now().strftime("%Y-%m-%d")
    )

    if not ocr_data:
        ocr_data = {
            "items": [],
            "store_name": receipt.store.name if receipt.store else "Unknown Store",
            "total_amount": receipt.total_amount or 0.0,
            "purchase_date": date_str,
            "image_filename": receipt.image_path.split("/")[-1] if receipt.image_path else None,
        }

    # OVERRIDE: If the DB has saved items, THEY are the source of truth.
    # This prevents corrupted or outdated ocr_data from messing up the Edit UI.
    if receipt.items:
        ocr_data["items"] = []
        for ri in receipt.items:
            item_notes = {}
            try:
                if ri.notes:
                    item_notes = json.loads(ri.notes)
            except Exception as e:
                logger.warning(
                    f"Failed to parse notes JSON for ReceiptItem {ri.id}: {e}. "
                    "Defaulting to empty notes."
                )

            # Map database ReceiptItem back to the format the Review UI expects
            item_dict = {
                "item_id": ri.item.id if ri.item else None,
                "name": ri.item.name if ri.item else "Unknown Item",
                "quantity": ri.quantity,
                "base_price": round(item_notes.get("base_price", ri.price * ri.quantity), 2),
                "final_price": round(ri.price * ri.quantity, 2),
                "weight": float(ri.weight) if ri.weight else None,
                "unit_type": ri.unit_type,
                "is_bulk": item_notes.get("is_bulk", False),
                "discounts": item_notes.get("discounts", []),
                "fees": item_notes.get("fees", []),
                "category": ri.item.category.name if ri.item and ri.item.category else "Other",
                "original_unit_price": ri.original_unit_price,
                "total_discount": ri.total_discount,
                "source": "db",  # Flag to indicate this came from already-saved data
            }

            if ri.item and getattr(ri.item, "fdc_id", None):
                item_dict["fdc_match"] = {
                    "fdc_id": ri.item.fdc_id,
                    "gtin": ri.item.gtin,
                    "description": "Saved USDA Match",
                }

            ocr_data["items"].append(item_dict)
    # Inject image filename if missing from stored ocr_data
    if receipt.image_path and "image_filename" not in ocr_data:
        ocr_data["image_filename"] = receipt.image_path.split("/")[-1]

    # Resolve sandbox item names to known library items so the review UI can
    # deep-link each matched line to its item insights page (auto-merged items
    # carry the canonical name but not the id).
    if ocr_data.get("items"):
        from app.models import Item
        from app.services.item_matcher import normalize_item_name

        unresolved = [i for i in ocr_data["items"] if not i.get("item_id") and i.get("name")]
        if unresolved:
            wanted = {normalize_item_name(i["name"]) for i in unresolved}
            rows = (
                db.query(Item.id, Item.normalized_name)
                .filter(Item.normalized_name.in_(wanted))
                .all()
            )
            by_norm = {norm: item_id for item_id, norm in rows}
            for i in unresolved:
                match_id = by_norm.get(normalize_item_name(i["name"]))
                if match_id:
                    i["item_id"] = match_id

    # FORCE UPDATE: Overwrite OCR data with current Database values
    # This ensures that if the user updated the store/date/total, the UI reflects it
    # instead of reverting to the original scan.
    if receipt.store:
        ocr_data["store_name"] = receipt.store.name

    if receipt.purchase_date:
        ocr_data["purchase_date"] = receipt.purchase_date.strftime("%Y-%m-%d")

    if receipt.total_amount is not None:
        ocr_data["total_amount"] = receipt.total_amount

    # Validation System
    detection_alert = None

    # 0. Check for OCR errors
    if ocr_error:
        detection_alert = {
            "type": "ocr_failed",
            "message": f"OCR Processing Failed ({ocr_error}). Please enter the receipt details manually.",
        }
    else:
        # 1. Check for duplicates
        from app.services.receipt_service import check_potential_duplicate

        duplicate_warning = check_potential_duplicate(db, receipt)
        if duplicate_warning:
            detection_alert = duplicate_warning

        # 2. Check for $0 total (only if no duplicate warning yet, to avoid clutter)
        elif not receipt.total_amount or receipt.total_amount == 0:
            detection_alert = {
                "type": "zero_total",
                "message": "Total amount is $0.00. Please verify the receipt total.",
            }

        # 3. Check for OCR line item total mismatch
        elif receipt.total_amount and ocr_data and ocr_data.get("items"):
            calc_total = sum(item.get("final_price") or 0.0 for item in ocr_data["items"])
            target_amount = ocr_data.get("subtotal") or receipt.total_amount

            # Allow for tax (usually < 10%) and rounding.
            # If difference is more than 15% of target and more than $2.00, show warning
            difference = abs(calc_total - target_amount)
            if difference > (target_amount * 0.15) and difference > 2.0:
                detection_alert = {
                    "type": "total_mismatch",
                    "message": f"Line items total (${calc_total:.2f}) doesn't match receipt total (${target_amount:.2f}). Please verify quantities and prices.",
                }

    # --- DATA AUGMENTATION (LIVE ENRICHMENT) ---
    # Perform a final pass to match OCR items against the LATEST master item list
    # and categorization history. This fixes test regressions and ensures UI accuracy.
    if ocr_data and "items" in ocr_data:
        from app.models import Item, ReceiptItem
        from app.services.item_matcher import get_best_match, get_store_item_ids

        # Pre-fetch all items and store purchase history for batch matching
        all_items = db.query(Item).all()
        store_item_ids = get_store_item_ids(db, receipt.store_id)

        for item_data in ocr_data["items"]:
            item_name = item_data.get("name", "")
            if not item_name:
                continue

            # Try to find existing item match
            master_item = get_best_match(
                item_name, db, threshold=90, existing_items=all_items, store_item_ids=store_item_ids
            )

            if master_item:
                # 1. Map to Master Name & Category
                if "original_ocr_name" not in item_data:
                    item_data["original_ocr_name"] = item_name

                item_data["name"] = master_item.name
                item_data["auto_merged"] = True

                if master_item.category:
                    item_data["category"] = master_item.category.name

                # 2. Inherit Historical Overrides (Feature 3)
                # Find the most recent receipt item for this master item
                hist_ri = (
                    db.query(ReceiptItem)
                    .filter(ReceiptItem.item_id == master_item.id)
                    .order_by(ReceiptItem.id.desc())
                    .first()
                )

                if hist_ri:
                    # Apply overrides if missing in current OCR or as preferred defaults
                    if hist_ri.quantity and not item_data.get("quantity"):
                        item_data["quantity"] = hist_ri.quantity

                    if hist_ri.weight and not item_data.get("weight"):
                        item_data["weight"] = float(hist_ri.weight)
                        item_data["unit_type"] = hist_ri.unit_type

                        # Inherit Bulk mode from notes if available
                        if hist_ri.notes:
                            try:
                                notes = json.loads(hist_ri.notes)
                                if notes.get("is_bulk"):
                                    item_data["is_bulk"] = True
                            except Exception as e:
                                logger.warning(f"Failed to parse receipt item notes JSON: {e}")

                        item_data["history_applied"] = True

    # Check if receipt file exists (Audit #20.UX)
    file_exists = False
    if receipt.image_path:
        path = Path(receipt.image_path)
        if path.is_absolute():
            file_exists = path.exists()
        else:
            # Fallback to data/uploads
            project_root = Path(__file__).resolve().parent.parent.parent
            file_path = project_root / "data" / "uploads" / path.name
            file_exists = file_path.exists()

    image_filename = Path(receipt.image_path).name if receipt.image_path else None

    return templates.TemplateResponse(
        request,
        "pages/receipt_review.html",
        {
            "receipt_id": receipt_id,
            "ocr_data": ocr_data,
            "detection_alert": detection_alert,
            "receipt": receipt,
            "file_status": {"exists": file_exists, "filename": image_filename},
            "categories": [
                {"id": c.id, "name": c.name}
                for c in db.query(Category).order_by(Category.name).all()
            ],
        },
    )


@router.get("/items", response_class=HTMLResponse)
def items_page(
    request: Request,
    tab: str = "all",
    category: int | None = None,
    db: Session = Depends(get_db),
):
    category_name = None
    if category:
        from app.models import Category

        cat = db.query(Category).filter(Category.id == category).first()
        category_name = cat.name if cat else None
    return templates.TemplateResponse(
        request,
        "pages/items.html",
        {
            "initial_tab": tab,
            "filter_category_id": category,
            "filter_category_name": category_name,
        },
    )


@router.get("/categories", response_class=HTMLResponse)
def categories_page(request: Request):
    return templates.TemplateResponse(request, "pages/categories.html")


@router.get("/trends", response_class=HTMLResponse)
def trends_page(request: Request):
    return templates.TemplateResponse(request, "pages/trends.html")


@router.get("/xray", response_class=HTMLResponse)
def xray_page(request: Request):
    """Receipt X-Ray — intelligence dashboard decoding hidden receipt data."""
    return templates.TemplateResponse(request, "pages/xray.html")


@router.get("/styleguide", response_class=HTMLResponse)
def styleguide_page(request: Request):
    """Internal living style guide — catalogs design tokens and UI components."""
    return templates.TemplateResponse(request, "pages/styleguide.html")


@router.get("/help/api-keys", response_class=HTMLResponse)
def api_keys_help_page(request: Request):
    """Novice-friendly guide to acquiring USDA FDC, Open Food Facts, and Gemini API keys."""
    return templates.TemplateResponse(request, "pages/api_keys_help.html")


@router.get("/demo-bi", response_class=HTMLResponse)
def demo_bi_page(request: Request):
    """BI demo — Tufte-style budget × nutrition intelligence dashboard with synthetic data."""
    return templates.TemplateResponse(request, "pages/demo_bi.html")


@router.get("/restock", response_class=HTMLResponse)
def restock_page(request: Request):
    """Restock predictions page — items due for repurchase with store price comparisons."""
    return templates.TemplateResponse(request, "pages/restock.html")


@router.get("/items/{item_id}/insights", response_class=HTMLResponse)
def item_insights_page(request: Request, item_id: int, db: Session = Depends(get_db)):
    from sqlalchemy.orm import joinedload

    from app.models.category import Category
    from app.models.item import Item
    from app.models.receipt import Receipt, ReceiptItem

    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        return templates.TemplateResponse(request, "pages/404.html", {"message": "Item not found"})

    # Load full purchase history, newest first
    purchase_history = (
        db.query(ReceiptItem)
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .filter(ReceiptItem.item_id == item.id)
        .filter(Receipt.purchase_date.isnot(None))
        .options(joinedload(ReceiptItem.receipt).joinedload(Receipt.store))
        .order_by(Receipt.purchase_date.desc())
        .all()
    )

    # Determine Nutrition Data and Source
    nutrition_source = item.nutrition_source or "auto"
    usda_raw = None
    unified_nutrition = {}

    # If it's a USDA item, fetch the raw data (it might have ingredients, etc.)
    if item.fdc_id:
        from app.services.fdc_service import fdc_service

        usda_raw = fdc_service.get_food_details(item.fdc_id)
        if not usda_raw and item.nutrients:
            # Fallback to cached
            usda_raw = {"foodNutrients": item.nutrients.get("foodNutrients", [])}

        # Foundation/SR Legacy payloads nest the category as an object;
        # flatten so the template can treat it as a plain string
        if usda_raw and isinstance(usda_raw.get("foodCategory"), dict):
            usda_raw["foodCategory"] = usda_raw["foodCategory"].get("description")

    # Get the effective nutrients (canonical + manual overrides)
    effective = item.effective_nutrients

    def _to_num(val):
        if val is None or val == "":
            return None
        if isinstance(val, int | float):
            return val
        try:
            val_str = str(val).strip()
            return int(val_str) if val_str.isdigit() else float(val_str)
        except (ValueError, TypeError):
            return None

    # Unified mapping for the template to consume easily
    unified_nutrition = {
        "calories": _to_num(effective.get("calories")),
        "fat": _to_num(effective.get("fat")),
        "saturatedFat": _to_num(effective.get("saturatedFat")),
        "transFat": _to_num(effective.get("transFat")),
        "cholesterol": _to_num(effective.get("cholesterol")),
        "sodium": _to_num(effective.get("sodium")),
        "carbohydrates": _to_num(effective.get("carbohydrates")),
        "fiber": _to_num(effective.get("fiber")),
        "sugars": _to_num(effective.get("sugars")),
        "protein": _to_num(effective.get("protein")),
    }

    # If using auto USDA and custom overrides aren't set, try to extract from raw USDA to populate the unified dict
    if usda_raw and nutrition_source == "auto":
        # Extract from labelNutrients first
        if usda_raw.get("labelNutrients"):
            ln = usda_raw["labelNutrients"]
            unified_nutrition["calories"] = unified_nutrition["calories"] or (
                ln.get("calories", {}).get("value") if ln.get("calories") else None
            )
            unified_nutrition["fat"] = unified_nutrition["fat"] or (
                ln.get("fat", {}).get("value") if ln.get("fat") else None
            )
            unified_nutrition["saturatedFat"] = unified_nutrition["saturatedFat"] or (
                ln.get("saturatedFat", {}).get("value") if ln.get("saturatedFat") else None
            )
            unified_nutrition["transFat"] = unified_nutrition["transFat"] or (
                ln.get("transFat", {}).get("value") if ln.get("transFat") else None
            )
            unified_nutrition["cholesterol"] = unified_nutrition["cholesterol"] or (
                ln.get("cholesterol", {}).get("value") if ln.get("cholesterol") else None
            )
            unified_nutrition["sodium"] = unified_nutrition["sodium"] or (
                ln.get("sodium", {}).get("value") if ln.get("sodium") else None
            )
            unified_nutrition["carbohydrates"] = unified_nutrition["carbohydrates"] or (
                ln.get("carbohydrates", {}).get("value") if ln.get("carbohydrates") else None
            )
            unified_nutrition["fiber"] = unified_nutrition["fiber"] or (
                ln.get("fiber", {}).get("value") if ln.get("fiber") else None
            )
            unified_nutrition["sugars"] = unified_nutrition["sugars"] or (
                ln.get("sugars", {}).get("value") if ln.get("sugars") else None
            )
            unified_nutrition["protein"] = unified_nutrition["protein"] or (
                ln.get("protein", {}).get("value") if ln.get("protein") else None
            )
        else:
            # Extract from foodNutrients
            for n in usda_raw.get("foodNutrients", []):
                n_name = n.get("nutrient", {}).get("name") or n.get("nutrientName")
                val = n.get("amount") if n.get("amount") is not None else n.get("value")
                if not val:
                    continue
                n_unit = (n.get("nutrient", {}).get("unitName") or n.get("unitName") or "").upper()
                # Foundation foods report "Energy (Atwater General Factors)" etc.
                if n_name and n_name.startswith("Energy") and n_unit == "KCAL":
                    unified_nutrition["calories"] = unified_nutrition["calories"] or val
                elif n_name == "Total lipid (fat)":
                    unified_nutrition["fat"] = unified_nutrition["fat"] or val
                elif n_name == "Fatty acids, total saturated":
                    unified_nutrition["saturatedFat"] = unified_nutrition["saturatedFat"] or val
                elif n_name == "Fatty acids, total trans":
                    unified_nutrition["transFat"] = unified_nutrition["transFat"] or val
                elif n_name == "Cholesterol":
                    unified_nutrition["cholesterol"] = unified_nutrition["cholesterol"] or val
                elif n_name == "Sodium, Na":
                    unified_nutrition["sodium"] = unified_nutrition["sodium"] or val
                elif n_name == "Carbohydrate, by difference":
                    unified_nutrition["carbohydrates"] = unified_nutrition["carbohydrates"] or val
                elif n_name == "Fiber, total dietary":
                    unified_nutrition["fiber"] = unified_nutrition["fiber"] or val
                elif n_name == "Total Sugars":
                    unified_nutrition["sugars"] = unified_nutrition["sugars"] or val
                elif n_name == "Protein":
                    unified_nutrition["protein"] = unified_nutrition["protein"] or val

    # Same for OpenFoodFacts extraction if it's OFF source
    if item.off_code and not usda_raw and nutrition_source == "auto":
        off_nutrients = item.nutrients or {}
        unified_nutrition["fat"] = unified_nutrition["fat"] or off_nutrients.get("fat_100g")
        unified_nutrition["saturatedFat"] = unified_nutrition["saturatedFat"] or off_nutrients.get(
            "saturated_fat_100g"
        )
        unified_nutrition["sodium"] = unified_nutrition["sodium"] or off_nutrients.get(
            "sodium_100g"
        )
        unified_nutrition["sugars"] = unified_nutrition["sugars"] or off_nutrients.get(
            "sugars_100g"
        )
        unified_nutrition["protein"] = unified_nutrition["protein"] or off_nutrients.get(
            "proteins_100g"
        )

    return templates.TemplateResponse(
        request,
        "pages/item_insights.html",
        {
            "item": item,
            "usda": usda_raw,
            "nutrition": unified_nutrition,
            "source": nutrition_source,
            "custom": item.custom_nutrients or {},
            "purchase_history": purchase_history,
            "categories": db.query(Category).order_by(Category.name).all(),
        },
    )


@router.get("/search", response_class=HTMLResponse)
def search_page(request: Request, q: str = "", db: Session = Depends(get_db)):
    """Full-page search results. Activated via Enter key or 'View all' link."""
    from app.api.search_router import _search_items

    q = q.strip()
    results = _search_items(q, db, limit=50) if len(q) >= 2 else []
    return templates.TemplateResponse(
        request,
        "pages/search_results_page.html",
        {"results": results, "query": q},
    )


@router.get("/produce", response_class=HTMLResponse)
def produce_page(request: Request):
    return templates.TemplateResponse(request, "pages/produce.html")


@router.get("/best-value/{category_type}", response_class=HTMLResponse)
def view_best_value_page(request: Request, category_type: str):
    """Full page for best value comparison"""
    from fastapi.responses import JSONResponse

    category_config = {
        "beverages": {"title": "Best Beverage Value", "unit": "$/oz"},
        "meat": {"title": "Best Meat Value", "unit": "$/lb"},
        "pantry": {"title": "Best Pantry Value", "unit": "$/oz"},
        "dairy": {"title": "Best Dairy Value", "unit": "$/oz"},
        "produce": {"title": "Best Produce Value", "unit": "$/lb"},
    }

    if category_type not in category_config:
        return JSONResponse({"error": "Invalid category"}, status_code=400)

    context = {
        "request": request,
        "title": category_config[category_type]["title"],
        "unit_label": category_config[category_type]["unit"],
        "category_type": category_type,
    }
    return templates.TemplateResponse(request, "pages/best_value.html", context)
