"""
OCR Service — Dual Backend
--------------------------
Controlled by the OCR_BACKEND environment variable:

  OCR_BACKEND=local   (default) — LLaVA via Ollama or LM Studio
  OCR_BACKEND=gemini             — Google Gemini API (original behavior)

Local backend env vars:
  OCR_BACKEND_URL=http://localhost:11434/v1   (Ollama default)
  OCR_MODEL=llava:7b                          (default, fits in 6GB VRAM)

Gemini backend env vars:
  GEMINI_API_KEY=<your key>
  GEMINI_MODEL_NAME=gemini-flash-latest        (optional override)
"""

import base64
import datetime
import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel as _SchemaBase

from app.services.pdf_parser import parse_pdf_receipt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------
def get_backend() -> str:
    """Dynamically lookup the OCR backend from environment."""
    return os.getenv("OCR_BACKEND", "local").lower()


# Usage tracker (used by both backends)
USAGE_TRACKER_FILE = Path("data/ocr_usage.json")
CACHE_DIR = Path("data/ocr_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# Global usage cache to avoid redundant disk reads (Audit #20.125)
_usage_cache: dict[str, Any] = {"date": None, "count": 0}
_usage_lock = threading.Lock()


def get_daily_usage() -> int:
    global _usage_cache
    with _usage_lock:
        try:
            today = datetime.date.today().isoformat()

            # Return cached value if matches today
            if _usage_cache["date"] == today:
                return int(_usage_cache["count"])

            if not USAGE_TRACKER_FILE.exists():
                return 0

            data = json.loads(USAGE_TRACKER_FILE.read_text())
            count = int(data.get("count", 0)) if data.get("date") == today else 0

            # Update cache
            _usage_cache["date"] = today
            _usage_cache["count"] = count
            return count
        except Exception as e:
            logger.warning(f"Error reading usage stats: {e}")
            return 0


def increment_daily_usage():
    global _usage_cache
    with _usage_lock:
        try:
            today = datetime.date.today().isoformat()
            current_count = 0
            if USAGE_TRACKER_FILE.exists():
                try:
                    data = json.loads(USAGE_TRACKER_FILE.read_text())
                    if data.get("date") == today:
                        current_count = data.get("count", 0)
                except Exception as e:
                    logger.warning(f"Error parsing usage tracker JSON: {e}")

            new_count = current_count + 1
            USAGE_TRACKER_FILE.write_text(json.dumps({"date": today, "count": new_count}))
            # Update cache
            _usage_cache["date"] = today
            _usage_cache["count"] = new_count
        except Exception as e:
            logger.warning(f"Error updating usage stats: {e}")


# ---------------------------------------------------------------------------
# Shared OCR prompt (used by both backends)
# ---------------------------------------------------------------------------
RECEIPT_PROMPT = """Extract grocery receipt data into JSON.
Output ONLY JSON. No markdown. No fences.

Fields:
- store_name: string
- purchase_date: YYYY-MM-DD
- total_amount: number
- subtotal: number
- tax: number
- items: list of {name, base_price, final_price, quantity, weight, unit_type, unit_price, is_bulk, discounts: [{amount, description}], fees: [{amount, description, type}]}

Rules:
1. base_price = The line total BEFORE discounts (usually Quantity * Unit Price). If the receipt has "Price" and "You Pay" columns, use "Price" as base_price.
2. final_price = The line total AFTER discounts and fees. If the receipt has "Price" and "You Pay" columns, use "You Pay" as final_price.
3. unit_price = The price per single unit (e.g., $2.49/lb or $1.99 each). If multiple prices exist (original and discounted), use the DISCOUNTED unit price.
4. If weights (lb/oz) exist ON THE RECEIPT LINE (e.g. "@ 2.49/lb"), extract weight, unit_type="lb", and set is_bulk=true.
5. Prime/Member savings = discounts. Make sure "Member Savings", "Basket Savings", etc. that appear below an item are associated with that item's discounts.
6. CRV/Deposits = fees (type: "crv"). If a CRV tax line appears immediately below an item, add it to that item's fees.
7. Combine multi-line items (item + its specific discounts and fees) into ONE single item entry.
8. PACKAGED WEIGHT ITEMS: If the item name contains a weight like "5LB", "2.5LB", "16OZ", etc., treat it as a packaged item sold by weight:
   - Set weight = the numeric value (e.g. 5), unit_type = the unit (e.g. "lb"), is_bulk = true
   - Set quantity = 1 (one package)
   - Set unit_price = final_price / weight (e.g. $3.99 / 5 = $0.80/lb)
   - Strip the weight from the name and clean it up (e.g. "RUSSET POT 5LB" → "RUSSET POTATOES")
   - Examples: "365WFM RUSSET POT 5LB" → weight=5, unit_type="lb", unit_price=final_price/5
9. is_bulk = true when the price is determined by weight (either from a per-lb receipt line or a packaged weight label). is_bulk = false for discrete units (cans, boxes, each).
10. Store Assignment for Amazon/Delivery: If the receipt is from Amazon.com (e.g. Order Summary) but contains "Whole Foods", "Whole Foods Market", "Wholefoods" or a physical Whole Foods address/pickup location (e.g. "Potrero Hill", "450 RHODE ISLAND ST"), set store_name to "Whole Foods Market".
11. CRITICAL: You MUST extract EVERY single purchased item on the receipt. Do NOT skip, consolidate, or summarize items. If there are 20 items on the receipt, your JSON array MUST contain exactly 20 items.
12. ITEM NAMES: Do NOT include quantity/price strings like "Qty: 1 @ $3.39 each" in the item name. The item name should only be the actual product description (e.g., "Organic Garnet Sweet Potato, 1 Each"). Ensure the name is separated from the quantity line.
"""


# ---------------------------------------------------------------------------
# Structured output schema — Gemini path only. Mirrors the prompt's field
# spec so the API is contractually bound to valid JSON; local models keep
# the json-repair fallback.
# ---------------------------------------------------------------------------


class _DiscountSchema(_SchemaBase):
    amount: float
    description: str


class _FeeSchema(_SchemaBase):
    amount: float
    description: str
    type: str


class _LineItemSchema(_SchemaBase):
    name: str
    base_price: float
    final_price: float
    quantity: float
    weight: float | None = None
    unit_type: str | None = None
    unit_price: float | None = None
    is_bulk: bool = False
    discounts: list[_DiscountSchema] = []
    fees: list[_FeeSchema] = []


class _ReceiptSchema(_SchemaBase):
    store_name: str
    purchase_date: str
    total_amount: float
    subtotal: float | None = None
    tax: float | None = None
    items: list[_LineItemSchema]


# ---------------------------------------------------------------------------
# JSON extraction helper (shared)
# ---------------------------------------------------------------------------
def _extract_json(raw: str) -> dict:
    """Pull a JSON object out of a LLaVA response, handling common quirks."""
    import json_repair  # handles LLM JSON quirks like missing commas, truncation

    text = raw.strip()

    # Strip markdown code fences: ```json ... ``` or ``` ... ```
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # Find the outermost JSON object
    if "{" in text:
        start = text.find("{")
        # Find the last closing brace to help with truncated outputs
        end = text.rfind("}")
        if end > start:
            text = text[start : end + 1]
        else:
            text = text[start:]
    else:
        logger.error(f"No JSON object found in response. Raw:\n{raw[:1000]}")
        raise json.JSONDecodeError("No JSON object found", raw, 0)

    # Try strict parse first, fall back to json_repair for malformed output
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"Strict JSON parse failed ({e}), trying json_repair...")
        data = json_repair.loads(text)
        if not isinstance(data, dict):
            raise json.JSONDecodeError(
                f"json_repair returned non-dict: {type(data)}", text, 0
            ) from e
        logger.info("json_repair successfully fixed malformed JSON")

    # Map inconsistent field names from smaller models to the expected schema
    data = _map_schema(data)

    if "store_name" in data and data["store_name"]:
        from app.services.store_utils import normalize_store_name

        data["store_name"] = normalize_store_name(data["store_name"])

    # Override store name to Whole Foods Market if it's an Amazon receipt with Whole Foods indicators
    store_name_lower = (data.get("store_name") or "").lower()
    if "amazon" in store_name_lower or store_name_lower in ["unknown store", ""]:
        raw_lower = raw.lower()
        if any(
            term in raw_lower
            for term in ["whole foods", "wholefoods", "450 rhode island", "potrero hill"]
        ):
            data["store_name"] = "Whole Foods Market"

    return data


def _map_schema(data: dict) -> dict:
    """Translate alternative field names into the project's canonical schema."""
    # Canonical mapping (case-insensitive keys)
    mapping = {
        "store location": "store_name",
        "store name": "store_name",
        "date of purchase": "purchase_date",
        "purchase date": "purchase_date",
        "date": "purchase_date",
        "net amount": "total_amount",
        "amount paid": "total_amount",
        "total cost": "total_amount",
        "total": "total_amount",
        "net": "total_amount",
        "grand total": "total_amount",
        "subtotal": "subtotal",
        "sub-total": "subtotal",
        "tax": "tax",
        "tax amount": "tax",
        "itemized list of items": "items",
        "items": "items",
    }

    # Standardize top-level keys
    current_keys = list(data.keys())
    for key in current_keys:
        lower_key = key.lower().strip()
        if lower_key in mapping:
            target = mapping[lower_key]
            if target not in data or not data[target]:
                data[target] = data.pop(key)

    # Item-level mapping
    if "items" in data and isinstance(data["items"], list):
        item_mapping = {
            "item": "name",
            "item name": "name",
            "description": "name",
            "name": "name",
            "unit price": "unit_price",
            "unit_price": "unit_price",
            "rate": "unit_price",
            "price": "unit_price",  # Map ambiguous 'price' to unit_price if possible
            "base_price": "base_price",
            "line total": "base_price",
            "total line price": "base_price",
            "total cost": "final_price",
            "total": "final_price",
            "cost": "final_price",
            "quantity": "quantity",
            "qty": "quantity",
            "amount": "final_price",
        }
        new_items = []
        for item in data["items"]:
            if not isinstance(item, dict):
                continue

            # Map item keys
            for ik, _iv in list(item.items()):
                lower_ik = ik.lower().strip()
                if lower_ik in item_mapping:
                    target = item_mapping[lower_ik]
                    if target not in item or not item[target]:
                        item[target] = item.pop(ik)

            # Ensure numeric fields are actually numbers
            for num_field in [
                "base_price",
                "final_price",
                "quantity",
                "weight",
                "unit_price",
            ]:
                val = item.get(num_field)
                if val is not None and isinstance(val, str):
                    try:
                        clean_val = val.replace("$", "").replace(",", "").strip()
                        item[num_field] = float(clean_val)
                    except ValueError:
                        pass

            # Logic to resolve conflicts between unit_price and base_price
            qty = item.get("quantity", 1) or 1
            up = item.get("unit_price")
            bp = item.get("base_price")
            fp = item.get("final_price")

            # If we have unit_price but no base_price (line total), calculate it
            if up is not None and bp is None:
                item["base_price"] = round(up * qty, 2)

            # If we have base_price but no unit_price, calculate it from base_price
            elif bp is not None and up is None and qty > 0:
                item["unit_price"] = round(bp / qty, 4)

            # If everything is missing except final_price, assume it's the base
            elif fp is not None and bp is None and up is None:
                item["base_price"] = fp
                item["unit_price"] = round(fp / qty, 4)

            # Always prefer final_price for unit_price when it's available
            # (final_price = actual price paid; base_price = MSRP before discounts)
            if fp is not None and qty > 0:
                item["unit_price"] = round(fp / qty, 4)

            # --- Size Extraction ---
            # Extract weights/counts from the item name if weight/unit_type are missing.
            # This catches packaged items like "RUSSET POT 5LB" where the AI missed it.
            if not item.get("weight") and not item.get("unit_type"):
                name = item.get("name", "")
                import re

                match = re.search(
                    r"([\d\.]+)\s*(oz|lb|g|kg|ml|l|gal|pt|qt|ct|pk)\b", name, re.IGNORECASE
                )
                if match:
                    try:
                        weight_val = float(match.group(1))
                        unit_val = match.group(2).lower()
                        item["weight"] = weight_val
                        item["unit_type"] = unit_val
                        item["is_bulk"] = True

                        # Recompute unit_price as final_price / weight (per-lb/oz price)
                        effective_price = fp if fp is not None else (bp or 0)
                        if weight_val > 0:
                            item["unit_price"] = round(effective_price / weight_val, 4)

                        # Strip the extracted size from the name
                        new_name = name[: match.start()] + name[match.end() :]
                        new_name = re.sub(r"\s+", " ", new_name).strip()
                        item["name"] = new_name
                    except ValueError:
                        pass
            elif item.get("weight") and item.get("unit_type"):
                # AI already found weight — ensure is_bulk is set and unit_price uses weight
                item["is_bulk"] = True
                effective_price = fp if fp is not None else (bp or 0)
                w = item["weight"]
                if w and w > 0:
                    item["unit_price"] = round(effective_price / w, 4)
            # --- End Size Extraction ---

            new_items.append(item)
        data["items"] = new_items

    # Cleanup top-level numbers
    for num_field in ["total_amount", "subtotal", "tax"]:
        val = data.get(num_field)
        if val is not None and isinstance(val, str):
            try:
                clean_val = val.replace("$", "").replace(",", "").strip()
                data[num_field] = float(clean_val)
            except ValueError:
                pass

    return data


def _error_result(msg: str) -> dict:
    return {
        "store_name": "Unknown Store",
        "purchase_date": None,
        "items": [],
        "total_amount": 0.0,
        "error": msg,
    }


# ===========================================================================
# LOCAL BACKEND  (LLaVA via Ollama or LM Studio)
# ===========================================================================

_local_client = None


def _get_local_client():
    global _local_client
    if _local_client is None:
        from openai import OpenAI

        url = os.getenv("OCR_BACKEND_URL", "http://localhost:11434/v1")
        # Increase timeout to 30 minutes (1800s) to prevent the client from dropping the connection
        # if a local "reasoning" model takes longer than the default 10 minutes to generate CoT tokens.
        _local_client = OpenAI(base_url=url, api_key="ollama", timeout=1800.0)
        logger.info(f"✓ Local OCR client initialized → {url}")
    return _local_client


def _image_to_base64(image_path: str) -> tuple[str, str]:
    """Return (mime_type, base64_string) for a given image path."""
    path = Path(image_path)
    ext = path.suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    mime = mime_map.get(ext, "image/jpeg")
    data = base64.b64encode(path.read_bytes()).decode("utf-8")
    return mime, data


# ---------------------------------------------------------------------------
# Local-backend image pre-processing
# ---------------------------------------------------------------------------
# Qwen2.5-VL and similar vision models divide images into fixed tiles (e.g. 448×448 px).
# A 400×3000 px receipt produces ~10 vertical tiles ≈ 2000+ image tokens, exhausting the
# KV-cache on modest VRAM.  We pre-process images *only* for the local backend:
#   1. Cap height at MAX_LOCAL_HEIGHT (preserving aspect ratio).
#   2. Convert to grayscale — receipt text has no meaningful colour information.
#   3. Re-encode as JPEG at controlled quality to reduce payload size.
# Gemini receives the original file (it handles large images natively).

_LOCAL_MAX_HEIGHT = int(os.getenv("LOCAL_OCR_MAX_HEIGHT", "1600"))  # pixels
_LOCAL_JPEG_QUALITY = int(os.getenv("LOCAL_OCR_JPEG_QUALITY", "85"))  # 1-95


def _preprocess_image_for_local(image_path: str) -> tuple[str, str]:
    """
    Resize and grayscale-convert a receipt image for the local vision model.

    Returns (mime_type, base64_jpeg_string).  Falls back to raw encoding if
    Pillow is unavailable or the image cannot be opened.
    """
    import io

    try:
        from PIL import Image
    except ImportError:
        logger.warning("[OCR] Pillow not available — skipping image pre-processing.")
        return _image_to_base64(image_path)

    try:
        with Image.open(image_path) as img:
            original_w, original_h = img.size

            # 1. Resize if taller than the cap (scale both axes proportionally)
            if original_h > _LOCAL_MAX_HEIGHT:
                scale = _LOCAL_MAX_HEIGHT / original_h
                new_w = max(1, int(original_w * scale))
                img = img.resize((new_w, _LOCAL_MAX_HEIGHT), Image.LANCZOS)
                logger.info(
                    f"[OCR] Resized {original_w}×{original_h} → {new_w}×{_LOCAL_MAX_HEIGHT} "
                    f"(scale={scale:.2f})"
                )
            else:
                logger.info(f"[OCR] Image {original_w}×{original_h} within limit — no resize.")

            # 2. Convert to grayscale (L) then back to RGB for JPEG compatibility
            img = img.convert("L").convert("RGB")

            # 3. Encode to JPEG in-memory
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=_LOCAL_JPEG_QUALITY, optimize=True)
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            logger.info(
                f"[OCR] Pre-processed image: {len(b64) // 1024} KB (quality={_LOCAL_JPEG_QUALITY})"
            )
            return "image/jpeg", b64

    except Exception as e:
        logger.warning(f"[OCR] Image pre-processing failed ({e}) — using raw image.")
        return _image_to_base64(image_path)


def _process_local(image_paths: list[str], prompt_extra: str = "") -> dict:
    """Call local LLaVA/Granite model via OpenAI-compatible API."""
    client = _get_local_client()
    url = os.getenv("OCR_BACKEND_URL", "http://localhost:11434/v1")

    # Auto-detect loaded model from LM Studio / Ollama to prevent static locking
    try:
        available = client.models.list()
        if available and available.data:
            model = available.data[0].id
            logger.info(f"[OCR] Auto-detected active local model: {model}")
        else:
            model = os.getenv("OCR_MODEL", "llava:7b")
    except Exception as e:
        logger.warning(f"[OCR] Failed to fetch active models ({e}). Falling back to .env.")
        model = os.getenv("OCR_MODEL", "llava:7b")

    logger.info("--- [OCR] LOCAL BACKEND START ---")
    logger.info(f"[OCR] Model:  {model}")
    logger.info(f"[OCR] Target: {url}")

    # Build content list: text prompt + all images
    content: list[dict[str, Any]] = [{"type": "text", "text": RECEIPT_PROMPT + prompt_extra}]

    encode_start = time.time()
    logger.info(f"[OCR] Encoding {len(image_paths)} image(s) (with pre-processing)...")
    for path in image_paths:
        try:
            mime, b64 = _preprocess_image_for_local(path)
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                }
            )
        except Exception as e:
            logger.warning(f"[OCR] Could not encode image {path}: {e}")

    encode_duration = time.time() - encode_start
    logger.info(f"[OCR] Encoding complete ({encode_duration:.2f}s)")
    logger.info("[OCR] Sending request to AI... (Waiting for response)")

    try:
        inference_start = time.time()
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            temperature=0.3,  # Qwen recommends 0.7 for instruct; we use 0.3 for structured JSON
            top_p=0.8,  # Qwen best practice: tighter sampling for deterministic output
            max_tokens=16384,  # Large receipts (40+ items) can exceed 4K tokens
            presence_penalty=1.5,  # Qwen best practice: prevents item repetition on long receipts
            # Note: top_k=20 is also recommended but not supported via OpenAI-compat API.
            # Configure top_k directly in LM Studio's model settings panel instead.
        )
        inference_duration = time.time() - inference_start
        raw = response.choices[0].message.content

        logger.info(f"[OCR] Inference complete ({inference_duration:.2f}s)")

        # Enhanced terminal output
        print("\n" + "=" * 60)
        print(f"--- [AI RAW RESPONSE: {model}] ---")
        print(raw)
        print("=" * 60 + "\n")

        data = _extract_json(raw)
        data["ocr_model"] = model
        return data
    except json.JSONDecodeError as e:
        logger.error(f"[OCR] JSON parse error: {e}")
        return _error_result(f"Failed to parse AI response as JSON: {e}")
    except Exception as e:
        logger.error(f"[OCR] Local AI error: {e}")
        return _error_result(str(e))


# ===========================================================================
# GEMINI BACKEND  (original implementation, preserved)
# ===========================================================================

_gemini_client = None
_gemini_model = None
_fallback_models: list[str] = []


def _init_gemini():
    global _gemini_client, _gemini_model, _fallback_models
    if _gemini_client is not None:
        return

    from google import genai

    from app.services.model_manager import model_manager

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY environment variable not set (required for OCR_BACKEND=gemini)"
        )

    _gemini_client = genai.Client(api_key=api_key)
    _gemini_model = os.getenv("GEMINI_MODEL_NAME") or model_manager.get_best_model(
        fallback="gemini-flash"
    )
    _fallback_models = model_manager.get_fallback_models()
    logger.info(f"✓ Gemini OCR client initialized. Primary model: {_gemini_model}")


def _make_gemini_generate(model, contents):
    """Single Gemini call — wrapped separately so tenacity can retry it."""
    from google.genai import types
    from google.genai.errors import ClientError

    try:
        return _gemini_client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_ReceiptSchema,
            ),
        )
    except ClientError as e:
        # Fail-soft: if this model/API version rejects the schema (400),
        # fall back to prompt-only JSON rather than losing the receipt
        if e.code == 400:
            logger.warning(f"Structured output rejected by {model} ({e}); retrying without schema")
            return _gemini_client.models.generate_content(model=model, contents=contents)
        raise


def _process_gemini(image_paths: list[str], prompt_extra: str = "") -> dict:
    """Call Google Gemini API (original implementation)."""
    _init_gemini()

    from google.genai.errors import ClientError
    from tenacity import (
        before_sleep_log,
        retry,
        retry_if_exception,
        stop_after_attempt,
        wait_exponential,
    )

    def is_retryable(e):
        return isinstance(e, ClientError) and (e.code == 429 or e.code >= 500)

    @retry(
        retry=retry_if_exception(is_retryable),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(2),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _generate_with_retry(model, contents):
        return _make_gemini_generate(model, contents)

    if not _gemini_client:
        return _error_result("Gemini client not initialized")

    # Upload images
    image_files = []
    for path in image_paths:
        img_file = _gemini_client.files.upload(file=path)
        logger.info(f"Uploaded to Gemini: {img_file.name}")
        image_files.append(img_file)

    # Build model list: primary + fallbacks, deduped
    models_to_try = list(
        dict.fromkeys([_gemini_model] + [m for m in _fallback_models if m != _gemini_model])
    )

    response = None
    last_error = None
    for model in models_to_try:
        logger.info(f"Attempting Gemini OCR with model: {model}")
        try:
            response = _generate_with_retry(model, [RECEIPT_PROMPT + prompt_extra] + image_files)
            logger.info(f"✓ Gemini OCR success with: {model}")
            break
        except Exception as e:
            logger.warning(f"✗ Gemini model {model} failed: {e}")
            last_error = e

    if response is None:
        return _error_result(f"All Gemini models failed. Last: {last_error}")

    try:
        data = _extract_json(response.text)
        data["ocr_model"] = model
        return data
    except json.JSONDecodeError as e:
        logger.error(f"Gemini JSON parse error: {e}")
        return _error_result("Failed to parse Gemini response as JSON")


# ===========================================================================
# PUBLIC API  — called by the rest of the app
# ===========================================================================


def _dispatch(image_paths: list[str], prompt_extra: str = "") -> dict:
    """Route to the correct backend based on OCR_BACKEND env var."""
    backend = get_backend()

    # 1. Check Cache First (keyed by file hash)
    try:
        # Calculate aggregate hash for all images
        hasher = hashlib.md5()
        for path in sorted(image_paths):
            if os.path.exists(path):
                hasher.update(Path(path).read_bytes())
        # Prompt is part of the key: learned corrections must invalidate stale results
        hasher.update((RECEIPT_PROMPT + prompt_extra).encode())
        file_hash = hasher.hexdigest()
        cache_path = CACHE_DIR / f"{file_hash}.json"

        if cache_path.exists():
            logger.info(f"[OCR] Cache hit! Using cached results for {file_hash}")
            cached_data = json.loads(cache_path.read_text())
            cached_data["cached"] = True
            return dict(cached_data)
    except Exception as e:
        logger.warning(f"[OCR] Cache error (reading): {e}")

    # 2. Dispatch to AI if not cached
    if backend == "gemini":
        logger.info(f"OCR backend: GEMINI ({len(image_paths)} image(s))")
        result = _process_gemini(image_paths, prompt_extra)
    else:
        # Show specific model in logs for local backend
        model = os.getenv("OCR_MODEL", "llava:7b")
        logger.info(f"OCR backend: LOCAL ({model}) ({len(image_paths)} image(s))")
        result = _process_local(image_paths, prompt_extra)

    # 3. Save to Cache
    if result and not result.get("error"):
        try:
            cache_path.write_text(json.dumps(result))
            logger.info(f"[OCR] Saved result to cache: {file_hash}")
        except Exception as e:
            logger.warning(f"[OCR] Cache error (writing): {e}")

    return result


def process_receipt_image(image_paths: str | list[str], prompt_extra: str = "") -> dict:
    """
    Process one or more receipt images and extract structured data.
    Routes to local LLaVA or Gemini based on OCR_BACKEND env var.
    """
    if isinstance(image_paths, str):
        paths = [image_paths]
    else:
        paths = image_paths

    logger.info(f"=== Starting OCR for: {paths} (backend={get_backend()}) ===")

    try:
        increment_daily_usage()
    except Exception as e:
        logger.warning(f"Failed to increment usage: {e}")

    return _dispatch(paths, prompt_extra)


def _check_amazon_logo(pdf_path: str, result: dict) -> dict:
    """Helper to reclassify Amazon.com receipts based on the logo in the PDF."""
    store_name = (result.get("store_name") or "").lower()
    if "amazon" in store_name:
        import os
        import subprocess

        from pdf2image import convert_from_path

        try:
            images = convert_from_path(pdf_path, dpi=200, first_page=1, last_page=1)
            if images:
                img = images[0]
                w, h = img.size
                crop_box = (w // 2, 0, w, int(h * 0.2))
                cropped = img.crop(crop_box)
                temp_img = f"temp_crop_ocr_{os.getpid()}.png"
                cropped.save(temp_img)
                ocr_out = (
                    subprocess.run(
                        ["tesseract", temp_img, "stdout"], capture_output=True, text=True
                    )
                    .stdout.lower()
                    .replace("\n", " ")
                )
                if "whole foods" in ocr_out:
                    result["store_name"] = "Whole Foods Market"
                    logger.info("PDF Logo OCR overriding store_name to Whole Foods Market")
                elif "fresh" in ocr_out:
                    result["store_name"] = "Amazon Fresh"
                    logger.info("PDF Logo OCR overriding store_name to Amazon Fresh")
                if os.path.exists(temp_img):
                    os.remove(temp_img)
        except Exception as e:
            logger.warning(f"Error checking PDF logo: {e}")
    return result


def process_pdf_receipt(pdf_path: str, prompt_extra: str = "") -> dict:
    """Process PDF receipt by first trying deterministic parsing, then falling back to OCR."""

    # Fast-Path Extraction (pdfplumber)
    fast_result = parse_pdf_receipt(pdf_path)
    if fast_result:
        logger.info(f"✓ Fast-Path Extract Successful for {pdf_path}")
        return _check_amazon_logo(pdf_path, fast_result)

    # Fallback to Original OCR logic
    temp_images = []
    try:
        from pdf2image import convert_from_path

        logger.info(f"Processing PDF: {pdf_path}")
        images = convert_from_path(pdf_path, dpi=300)

        if not images:
            logger.error("No images extracted from PDF")
            return _error_result("No images extracted from PDF")

        base_name = pdf_path.replace(".pdf", "")
        for i, image in enumerate(images):
            temp_image = f"{base_name}_page{i + 1}.jpg"
            image.save(temp_image, "JPEG")
            temp_images.append(temp_image)
            logger.info(f"Saved temp page: {temp_image}")

        ocr_result = process_receipt_image(temp_images, prompt_extra)
        return _check_amazon_logo(pdf_path, ocr_result)

    except Exception as e:
        logger.error(f"PDF processing error: {e}")
        import traceback

        traceback.print_exc()
        return _error_result(str(e))

    finally:
        for temp_image in temp_images:
            if os.path.exists(temp_image):
                os.remove(temp_image)
                logger.info(f"Cleaned up temp image: {temp_image}")


def process_receipt_task(receipt_id: int, image_path: str):
    """
    Background task: run OCR and update the database.
    Called from the upload endpoint via FastAPI BackgroundTasks.
    """
    from app.database import SessionLocal
    from app.models import Receipt, Store

    backend = get_backend()
    logger.info(f"Background OCR task started for receipt {receipt_id} (backend={backend})")
    db = SessionLocal()
    try:
        receipt = db.query(Receipt).filter(Receipt.id == receipt_id).first()
        if not receipt:
            logger.error(f"Receipt {receipt_id} not found in background task")
            return

        file_ext = Path(image_path).suffix.lower()
        start_time = time.time()

        # Few-shot feedback: recent human corrections, scoped to this receipt's
        # store when known (reprocess), global otherwise (first pass)
        prompt_extra = ""
        try:
            from app.services.correction_service import get_correction_prompt

            store_hint = receipt.store.name if receipt.store else None
            prompt_extra = get_correction_prompt(db, store_hint)
            if prompt_extra:
                logger.info(f"Injecting learned corrections into OCR prompt (store={store_hint})")
        except Exception as e:
            logger.warning(f"Could not build correction prompt: {e}")

        try:
            if file_ext == ".pdf":
                ocr_result = process_pdf_receipt(image_path, prompt_extra)
            else:
                ocr_result = process_receipt_image(image_path, prompt_extra)
        except Exception as e:
            logger.error(f"OCR error for receipt {receipt_id}: {e}")
            receipt.status = "failed"
            receipt.error_message = str(e)
            db.commit()
            return

        duration = time.time() - start_time
        logger.info(f"OCR finished for receipt {receipt_id} in {duration:.2f}s")

        if ocr_result.get("error"):
            receipt.status = "failed"
            receipt.error_message = ocr_result["error"]
            db.commit()
            return

        ocr_result["processing_time_seconds"] = round(duration, 2)
        backend_type = get_backend()
        ocr_result["ocr_backend"] = backend_type  # Tag which backend was used

        if "ocr_model" not in ocr_result:
            if backend_type == "gemini":
                ocr_result["ocr_model"] = os.getenv("GEMINI_MODEL_NAME", "gemini-1.5-flash")
            else:
                ocr_result["ocr_model"] = os.getenv("OCR_MODEL", "qwen/qwen2.5-vl-7b")

        receipt.ocr_data = json.dumps(ocr_result)

        if ocr_result.get("total_amount"):
            receipt.total_amount = ocr_result["total_amount"]

        if ocr_result.get("purchase_date"):
            try:
                receipt.purchase_date = datetime.datetime.strptime(
                    ocr_result["purchase_date"], "%Y-%m-%d"
                )
            except Exception as e:
                logger.warning(
                    f"Failed to parse purchase_date '{ocr_result.get('purchase_date')}' "
                    f"from OCR results for receipt {receipt_id}: {e}"
                )

        if ocr_result.get("store_name"):
            from app.services.store_utils import normalize_store_name

            store_name = normalize_store_name(ocr_result["store_name"])
            store = db.query(Store).filter(Store.name == store_name).first()
            if not store:
                store = Store(name=store_name)
                db.add(store)
                db.commit()
                db.refresh(store)
            receipt.store_id = store.id

        if ocr_result.get("order_number"):
            # Check for existing receipt with this order_number to avoid UNIQUE constraint crash
            existing = (
                db.query(Receipt)
                .filter(
                    Receipt.order_number == ocr_result["order_number"], Receipt.id != receipt.id
                )
                .first()
            )
            if existing:
                logger.warning(
                    f"Order number {ocr_result['order_number']} already exists on receipt {existing.id}. "
                    f"Skipping order_number assignment for receipt {receipt_id}."
                )
            else:
                receipt.order_number = ocr_result["order_number"]

        # START ENRICHMENT: Local Match + AI Categorization
        try:
            from rapidfuzz import fuzz

            from app.models import Item, ReceiptItem
            from app.services.category_tagger import categorize_items_batch
            from app.services.item_matcher import normalize_item_name

            all_db_items = db.query(Item).all()
            unknown_items = []

            for item in ocr_result.get("items", []):
                item_name = item.get("name", "")
                if not item_name:
                    continue

                normalized = normalize_item_name(item_name)
                exact_match = next(
                    (it for it in all_db_items if it.normalized_name == normalized), None
                )

                best_match = exact_match
                best_score = 100 if exact_match else 0

                # Only fuzzy search if no exact match
                if not exact_match:
                    for db_item in all_db_items:
                        score = fuzz.token_sort_ratio(str(normalized), str(db_item.normalized_name))
                        if score > best_score:
                            best_score = int(score)
                            best_match = db_item

                # Feature 2 & 3: Auto-merge & History Overrides
                if best_match and best_score >= 95:
                    if item["name"] != best_match.name:
                        original_name = item["name"]
                        item["original_ocr_name"] = original_name
                        item["name"] = best_match.name
                        item["auto_merged"] = True
                        logger.info(
                            f"✨ Auto-merged OCR item '{original_name}' -> '{best_match.name}' "
                            f"(fuzzy score: {best_score})"
                        )

                    # Feature 1: Inherit Category
                    if best_match.category:
                        item["category"] = best_match.category.name

                    # Feature 3: Pull historical overrides (quantity, weight, units)
                    # Only apply if the current quantity is 1.0 (default),
                    # to avoid overwriting high-confidence quantities found by the PDF parser.
                    recent_entry = (
                        db.query(ReceiptItem)
                        .filter(ReceiptItem.item_id == best_match.id)
                        .order_by(ReceiptItem.id.desc())
                        .first()
                    )

                    if recent_entry and item.get("quantity", 1.0) == 1.0:
                        applied_history = False
                        if recent_entry.quantity and recent_entry.quantity != 1.0:
                            item["quantity"] = recent_entry.quantity
                            applied_history = True
                        if recent_entry.weight:
                            item["weight"] = recent_entry.weight
                            applied_history = True
                        if recent_entry.unit_type:
                            item["unit_type"] = recent_entry.unit_type
                            applied_history = True

                        if applied_history:
                            item["history_applied"] = True

                elif best_match and best_score >= 80:
                    # Fallback to manual suggestion
                    item["suggestion"] = {"id": best_match.id, "name": best_match.name}

                # Queue for Feature 1 (AI Batch Categorization) if not mapped above
                if not item.get("category"):
                    unknown_items.append(item)

            # Feature 1: Fast Batch AI categorization for completely new items
            if unknown_items:
                # Add delay to avoid immediate 429 exhaustion on free tier API
                time.sleep(1)
                names_to_categorize = [i["name"] for i in unknown_items]
                try:
                    category_map = categorize_items_batch(names_to_categorize)
                    for i in unknown_items:
                        i["category"] = category_map.get(i["name"], "Other")
                except Exception as ce:
                    logger.warning(
                        f"Batch AI categorization failed: {ce}. Falling back to 'Other'."
                    )
                    for i in unknown_items:
                        i["category"] = "Other"

            # Feature 4: USDA FoodData Central Enrichment (Branded Product Lookup)
            from app.services.fdc_service import fdc_service

            for item in ocr_result.get("items", []):
                # Skip if we already have a high-confidence local match
                if item.get("auto_merged"):
                    continue

                # Skip garbage OCR text (e.g. Amazon recommendation sections)
                item_name = item.get("name", "")
                if len(item_name) > 150:
                    logger.warning(
                        f"Skipping FDC for junk item name ({len(item_name)} chars): {item_name[:80]}..."
                    )
                    continue

                # Try FDC enrichment to get Brand, GTIN, and Canonical Description
                try:
                    fdc_data = fdc_service.enrich_item_data(item_name)
                    if fdc_data:
                        item["fdc_match"] = fdc_data
                        # If FDC category is more specific than "Other" or generic AI guess, override it
                        if fdc_data.get("category") and (
                            not item.get("category") or item.get("category") in ["Other", "General"]
                        ):
                            item["category"] = fdc_data["category"]
                        logger.info(
                            f"  ✨ USDA Match found for '{item_name}' -> '{fdc_data['description']}'"
                        )
                except Exception as e:
                    logger.warning(f"FDC enrichment failed for item '{item_name}': {e}")

            # Update DB with fully enriched data
            receipt.ocr_data = json.dumps(ocr_result)

        except Exception as e:
            logger.error(f"Post-OCR taxonomy enrichment failed: {e}")
        # END ENRICHMENT

        # Duplicate Detection
        from app.services.receipt_service import check_potential_duplicate

        duplicate_info = check_potential_duplicate(db, receipt)
        if duplicate_info:
            if "order number" in duplicate_info["message"].lower():
                logger.info(
                    f"⚠ Aborting processing. Receipt {receipt_id} is an exact Order ID duplicate."
                )
                receipt.status = "duplicate"
                receipt.error_message = duplicate_info["message"]
                db.commit()
                return

            ocr_result["duplicate_warning"] = duplicate_info
            receipt.ocr_data = json.dumps(ocr_result)
            logger.info(f"⚠ Receipt {receipt_id} flagged as potential duplicate")

        receipt.status = "completed"
        db.commit()
        logger.info(f"✓ Receipt {receipt_id} OCR complete ({get_backend()} backend)")

    except Exception as e:
        logger.error(f"Background task failed for receipt {receipt_id}: {e}")
        if receipt:
            try:
                receipt.status = "failed"
                receipt.error_message = f"System Error: {str(e)}"
                db.commit()
            except Exception:
                pass
    finally:
        db.close()
