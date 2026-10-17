"""Product title cleaning, fuzzy/GTIN matching, and unit-price comparison for the
TruePriceMemory browser extension.

Kept separate from ``app.services.item_matcher`` so receipt OCR ingestion keeps
its existing ``token_sort_ratio`` thresholds untouched while the extension gets
retail-title normalization and subset-aware scoring.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy.orm import Session, joinedload

from app.models import Item, Receipt, ReceiptItem, Store
from app.services.item_matcher import STORE_CONTEXT_RANK_BOOST, get_store_item_ids
from app.services.spend import comparable_price_series, comparable_unit_price, price_basis_label
from app.services.store_utils import normalize_store_name
from app.utils.item_parsing import COUNT_UNITS

DEFAULT_THRESHOLD = 70
DEFAULT_LIMIT = 3
MAX_LIMIT = 10
HISTORY_LIMIT = 12

# Retailer house-brand prefixes that add noise to product titles on Amazon Fresh
# and Safeway without changing what the product actually is.
_STORE_BRAND_PREFIXES = (
    r"365\s+by\s+whole\s+foods\s+market",
    r"whole\s+foods\s+market",
    r"amazon\s+brand\s*[-–—]?\s*happy\s+belly",
    r"amazon\s+brand\s*[-–—]?\s*solimo",
    r"amazon\s+fresh",
    r"happy\s+belly",
    r"signature\s+select",
    r"signature\s+farms",
    r"signature\s+care",
    r"o\s+organics",
    r"open\s+nature",
)

_BRAND_PREFIX_RE = re.compile(
    r"^\s*(?:" + "|".join(_STORE_BRAND_PREFIXES) + r")\b[\s,:-]*",
    re.IGNORECASE,
)

# Parenthetical expressions that carry pack/size metadata rather than product identity.
_PAREN_PACK_RE = re.compile(
    r"\((?:[^)]*\b(?:pack|pk|count|ct|oz|ounce|lb|pound|liter|litre|ml|gal|g|kg)\b[^)]*)\)",
    re.IGNORECASE,
)

# Inline size/count phrases: "1 Liter", "16 Ounce", "5.3 oz", "18 Count", "Pack of 6", "6-Pack".
_SIZE_TOKEN_RE = re.compile(
    r"\b(?:"
    r"pack\s+of\s+\d+"
    r"|\d+\s*[-–]?\s*(?:pack|pk|count|ct|cnt)\b"
    r"|\d+(?:\.\d+)?\s*(?:x\s*\d+(?:\.\d+)?)?\s*"
    r"(?:fl\.?\s*oz\.?|fluid\s+ounces?|ounces?|oz\.?|pounds?|lbs?\.?|grams?|g|kilograms?|kg"
    r"|milliliters?|ml|liters?|litres?|l|gallons?|gal|quarts?|qt|pints?|pt)\b"
    r")",
    re.IGNORECASE,
)

# Packaging nouns left behind once the numbers and units are removed.
_CONTAINER_WORDS = frozenset(
    {
        "bottle",
        "bottles",
        "can",
        "cans",
        "jar",
        "jars",
        "box",
        "boxes",
        "bag",
        "bags",
        "carton",
        "cartons",
        "tub",
        "tubs",
        "cup",
        "cups",
        "pouch",
        "pouches",
        "container",
        "containers",
        "package",
        "packages",
        "pack",
        "packs",
    }
)

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

# Conversions to ounces (weight or fluid ounces) so sizes on the page can be
# compared with the dominant basis stored in receipt_items.
_TO_OZ: dict[str, float] = {
    "oz": 1.0,
    "fl oz": 1.0,
    "lb": 16.0,
    "g": 1.0 / 28.3495,
    "kg": 35.27396,
    "ml": 1.0 / 29.5735,
    "l": 33.814,
    "pt": 16.0,
    "qt": 32.0,
    "gal": 128.0,
}


@dataclass(frozen=True)
class ParsedRetailSize:
    amount: float
    unit: str
    pack_count: int = 1
    total_oz: float | None = None
    total_count: float | None = None


def clean_retail_title(title: str) -> str:
    """Strip retailer house-brand prefixes, size/pack tokens, and packaging nouns."""
    if not title:
        return ""

    text = _BRAND_PREFIX_RE.sub(" ", title.strip())
    text = _PAREN_PACK_RE.sub(" ", text)
    text = _SIZE_TOKEN_RE.sub(" ", text)
    text = _NON_ALNUM_RE.sub(" ", text.lower())

    tokens = [tok for tok in text.split() if tok not in _CONTAINER_WORDS]
    if tokens:
        return " ".join(tokens)

    # Fallback if the input was purely size/container words.
    return _NON_ALNUM_RE.sub(" ", title.lower()).strip()


def _canon_unit(raw_unit: str) -> str:
    u = re.sub(r"\s+", " ", raw_unit.lower().replace(".", "").strip())
    if u in {"fl oz", "floz", "fluid ounce", "fluid ounces"}:
        return "fl oz"
    if u in {"oz", "ounce", "ounces"}:
        return "oz"
    if u in {"lb", "lbs", "pound", "pounds"}:
        return "lb"
    if u in {"g", "gram", "grams"}:
        return "g"
    if u in {"kg", "kilogram", "kilograms"}:
        return "kg"
    if u in {"ml", "milliliter", "milliliters"}:
        return "ml"
    if u in {"l", "liter", "liters", "litre", "litres"}:
        return "l"
    if u in {"gal", "gallon", "gallons"}:
        return "gal"
    if u in {"qt", "quart", "quarts"}:
        return "qt"
    if u in {"pt", "pint", "pints"}:
        return "pt"
    return u


def parse_retail_size(text: str | None) -> ParsedRetailSize | None:
    """Extract package weight/volume and multi-pack count from a retail title or size string."""
    if not text:
        return None

    pack_count = 1
    pack_match = re.search(
        r"(?:pack\s+of\s+(\d+)|(\d+)\s*[-–]?\s*(?:pack|pk)\b|(\d+)\s*(?:ct|count)\b\s*,?)",
        text,
        re.IGNORECASE,
    )
    if pack_match:
        found = next((g for g in pack_match.groups() if g is not None), None)
        if found:
            pack_count = max(1, int(found))
    else:
        mult_match = re.search(r"\b(\d+)\s*x\s*\d+(?:\.\d+)?", text, re.IGNORECASE)
        if mult_match:
            pack_count = max(1, int(mult_match.group(1)))

    measure_match = re.search(
        r"(\d+(?:\.\d+)?)\s*"
        r"(fl\.?\s*oz\.?|fluid\s+ounces?|ounces?|oz\.?|pounds?|lbs?\.?|grams?|g|kilograms?|kg"
        r"|milliliters?|ml|liters?|litres?|l|gallons?|gal|quarts?|qt|pints?|pt)\b",
        text,
        re.IGNORECASE,
    )
    if measure_match:
        amount = float(measure_match.group(1))
        unit = _canon_unit(measure_match.group(2))
        factor = _TO_OZ.get(unit)
        total_oz = round(amount * factor * pack_count, 4) if factor else None
        return ParsedRetailSize(
            amount=amount,
            unit=unit,
            pack_count=pack_count,
            total_oz=total_oz,
            total_count=float(pack_count) if pack_count > 1 else None,
        )

    count_match = re.search(
        r"(?:(\d+(?:\.\d+)?)\s*(?:count|ct|cnt|pk|pack)\b|pack\s+of\s+(\d+))",
        text,
        re.IGNORECASE,
    )
    if count_match:
        raw_cnt = count_match.group(1) or count_match.group(2)
        cnt = float(raw_cnt)
        if cnt > 0:
            return ParsedRetailSize(
                amount=cnt,
                unit="ct",
                pack_count=int(cnt),
                total_oz=None,
                total_count=cnt,
            )

    return None


def _normalize_gtin(gtin: str | None) -> str:
    if not gtin:
        return ""
    digits = re.sub(r"\D+", "", gtin).lstrip("0")
    return digits


def score_retail_match(cleaned_query: str, item_name: str) -> int:
    """Similarity score (0-100) between a cleaned retail query and an item name.

    Uses ``token_sort_ratio`` blended with subset-aware token overlap so verbose
    retail titles match concise item names (and vice versa) without letting a
    single generic word like "Water" score 100 against "Schweppes Tonic Water".
    """
    item_clean = clean_retail_title(item_name)
    if not cleaned_query or not item_clean:
        return 0
    if cleaned_query == item_clean:
        return 100

    sort_score = float(fuzz.token_sort_ratio(cleaned_query, item_clean))
    q_tokens = {t for t in cleaned_query.split() if len(t) > 1}
    i_tokens = {t for t in item_clean.split() if len(t) > 1}
    if not q_tokens or not i_tokens:
        return int(round(sort_score))

    shared = q_tokens & i_tokens
    if not shared:
        return int(round(sort_score * 0.7))

    # Multi-word subset: e.g. query "schweppes tonic water" vs item "tonic water"
    # or user-selected "tonic water" vs item "schweppes tonic water".
    if len(shared) >= 2 and (i_tokens <= q_tokens or q_tokens <= i_tokens):
        smaller = min(len(q_tokens), len(i_tokens))
        larger = max(len(q_tokens), len(i_tokens))
        coverage = smaller / larger
        subset_score = 88.0 + 10.0 * coverage
        return int(round(min(99.0, max(sort_score, subset_score))))

    # Single-word query or item that is a subset of a 2-word counterpart
    # (e.g. "eggs" vs "large eggs"), but never a 1-word item against a 3+ word query.
    if len(shared) == 1 and (i_tokens <= q_tokens or q_tokens <= i_tokens):
        larger = max(len(q_tokens), len(i_tokens))
        if larger == 2:
            return int(round(max(sort_score, 78.0)))
        return int(round(min(sort_score, 60.0)))

    set_score = float(fuzz.token_set_ratio(cleaned_query, item_clean))
    jaccard = len(shared) / len(q_tokens | i_tokens)
    blended = max(sort_score, set_score * (0.55 + 0.45 * jaccard))
    return int(round(min(99.0, blended)))


def compare_page_offer(
    *,
    basis: str,
    comparable_past_price: float | None,
    page_price: float | None,
    parsed_size: ParsedRetailSize | None,
) -> dict[str, Any] | None:
    """Compare the current page price against the item's historical price basis."""
    if page_price is None or page_price <= 0:
        return None

    label = price_basis_label(basis)
    page_unit_price: float | None = None
    compatible = False

    if basis in _TO_OZ:
        if parsed_size is not None and parsed_size.total_oz and parsed_size.total_oz > 0:
            basis_in_oz = _TO_OZ[basis]
            amount_in_basis = parsed_size.total_oz / basis_in_oz
            if amount_in_basis > 0:
                page_unit_price = round(page_price / amount_in_basis, 4)
                compatible = True
    elif basis in COUNT_UNITS:
        if parsed_size is not None and parsed_size.total_count and parsed_size.total_count > 0:
            page_unit_price = round(page_price / parsed_size.total_count, 4)
            compatible = True
    elif not basis or basis == "each":
        if parsed_size is None or parsed_size.pack_count == 1:
            page_unit_price = round(page_price, 4)
            compatible = True
        elif parsed_size.total_count and parsed_size.total_oz is None:
            page_unit_price = round(page_price / parsed_size.total_count, 4)
            compatible = True

    delta_pct: float | None = None
    verdict: str | None = None
    if (
        compatible
        and page_unit_price is not None
        and comparable_past_price
        and comparable_past_price > 0
    ):
        delta_pct = round(
            ((page_unit_price - comparable_past_price) / comparable_past_price) * 100.0,
            1,
        )
        if delta_pct <= -5.0:
            verdict = "good_deal"
        elif delta_pct >= 5.0:
            verdict = "pricier"
        else:
            verdict = "typical"

    return {
        "page_price": round(page_price, 2),
        "page_unit_price": round(page_unit_price, 4) if page_unit_price is not None else None,
        "comparable_past_price": (
            round(comparable_past_price, 4) if comparable_past_price is not None else None
        ),
        "basis": basis or "each",
        "basis_label": label,
        "unit_compatible": compatible,
        "delta_pct": delta_pct,
        "verdict": verdict,
    }


def lookup_items(
    db: Session,
    *,
    q: str = "",
    store: str | None = None,
    size: str | None = None,
    price: float | None = None,
    gtin: str | None = None,
    limit: int = DEFAULT_LIMIT,
    threshold: int = DEFAULT_THRESHOLD,
) -> dict[str, Any]:
    """Find matching items and build their per-store and all-store price summaries."""
    capped_limit = max(1, min(limit, MAX_LIMIT))
    cleaned_q = clean_retail_title(q)
    canonical_store = normalize_store_name(store) if store and store.strip() else None

    store_item_ids: set[int] = set()
    if canonical_store:
        store_row = db.query(Store).filter(Store.name == canonical_store).first()
        if store_row:
            store_item_ids = get_store_item_ids(db, store_row.id)

    all_items = db.query(Item).all()
    norm_gtin = _normalize_gtin(gtin)

    candidates: list[dict[str, Any]] = []
    for item in all_items:
        if norm_gtin and _normalize_gtin(item.gtin) == norm_gtin:
            candidates.append({"item": item, "confidence": 100, "matched_by": "gtin"})
            continue

        if not cleaned_q:
            continue

        score = score_retail_match(cleaned_q, str(item.normalized_name or item.name or ""))
        if score >= threshold:
            candidates.append({"item": item, "confidence": score, "matched_by": "name"})

    def _rank_key(entry: dict[str, Any]) -> tuple[int, float, int]:
        is_gtin = 1 if entry["matched_by"] == "gtin" else 0
        rank_score = float(entry["confidence"])
        if store_item_ids and entry["item"].id in store_item_ids:
            rank_score += STORE_CONTEXT_RANK_BOOST
        return (is_gtin, rank_score, int(entry["confidence"]))

    candidates.sort(key=_rank_key, reverse=True)
    # Fetch history in a single batch query for top candidates (avoiding N+1).
    top_candidates = candidates[: capped_limit * 2]
    top_ids = [c["item"].id for c in top_candidates]

    lines_by_item: dict[int, list[ReceiptItem]] = {item_id: [] for item_id in top_ids}
    if top_ids:
        rows = (
            db.query(ReceiptItem)
            .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
            .options(joinedload(ReceiptItem.receipt).joinedload(Receipt.store))
            .filter(
                ReceiptItem.item_id.in_(top_ids),
                ReceiptItem.price.is_not(None),
                ReceiptItem.price > 0,
            )
            .all()
        )
        for ri in rows:
            if ri.item_id in lines_by_item:
                lines_by_item[ri.item_id].append(ri)

    parsed_size = parse_retail_size(size) or parse_retail_size(q)
    matches: list[dict[str, Any]] = []

    for entry in top_candidates:
        if len(matches) >= capped_limit:
            break
        item = entry["item"]
        item_lines = lines_by_item.get(item.id, [])
        if not item_lines:
            continue

        # Order newest purchase first; fall back to receipt id when purchase_date is missing.
        item_lines.sort(
            key=lambda r: (
                r.receipt.purchase_date or datetime.min if r.receipt else datetime.min,
                r.receipt_id or 0,
                r.id or 0,
            ),
            reverse=True,
        )

        basis, series = comparable_price_series(item_lines)
        basis = basis or "each"
        basis_label = price_basis_label(basis)

        # Build history (newest 12)
        history: list[dict[str, Any]] = []
        for line in item_lines[:HISTORY_LIMIT]:
            receipt = line.receipt
            s_name = (
                receipt.store.name
                if receipt and receipt.store and receipt.store.name
                else "Unknown Store"
            )
            p_date = (
                receipt.purchase_date.strftime("%Y-%m-%d")
                if receipt and receipt.purchase_date
                else None
            )
            u_price, _u_basis = comparable_unit_price(line)
            history.append(
                {
                    "date": p_date,
                    "store": s_name,
                    "price": round(float(line.price or 0.0), 2),
                    "unit_price": round(float(u_price), 4),
                    "quantity": float(line.quantity or 1.0),
                    "weight": float(line.weight) if line.weight is not None else None,
                    "unit": line.unit_type,
                }
            )

        newest = history[0]
        last_paid = {
            "price": newest["price"],
            "unit_price": newest["unit_price"],
            "basis": basis,
            "basis_label": basis_label,
            "store": newest["store"],
            "date": newest["date"],
        }

        # All-stores summary (raw per-package price and comparable unit price)
        all_prices = [float(line.price) for line in item_lines if line.price and line.price > 0]
        best_line = min(item_lines, key=lambda r: float(r.price or 0.0))
        best_receipt = best_line.receipt
        best_store_name = (
            best_receipt.store.name
            if best_receipt and best_receipt.store and best_receipt.store.name
            else "Unknown Store"
        )
        best_date = (
            best_receipt.purchase_date.strftime("%Y-%m-%d")
            if best_receipt and best_receipt.purchase_date
            else None
        )
        all_stores = {
            "min_price": round(min(all_prices), 2),
            "max_price": round(max(all_prices), 2),
            "avg_price": round(sum(all_prices) / len(all_prices), 2),
            "best_store": best_store_name,
            "best_price": round(float(best_line.price or 0.0), 2),
            "best_date": best_date,
            "total_purchases": len(item_lines),
        }

        # Current-store summary when store parameter is given
        at_this_store: dict[str, Any] | None = None
        if canonical_store:
            store_lines = [
                line
                for line in item_lines
                if line.receipt
                and line.receipt.store
                and line.receipt.store.name == canonical_store
            ]
            if store_lines:
                s_prices = [float(line.price) for line in store_lines if line.price]
                first_s = store_lines[0]
                first_s_uprice, _ = comparable_unit_price(first_s)
                first_s_date = (
                    first_s.receipt.purchase_date.strftime("%Y-%m-%d")
                    if first_s.receipt and first_s.receipt.purchase_date
                    else None
                )
                at_this_store = {
                    "store": canonical_store,
                    "last_price": round(float(first_s.price or 0.0), 2),
                    "last_unit_price": round(float(first_s_uprice), 4),
                    "last_date": first_s_date,
                    "min_price": round(min(s_prices), 2),
                    "avg_price": round(sum(s_prices) / len(s_prices), 2),
                    "count": len(store_lines),
                }

        comparable_avg = sum(val for _line, val in series) / len(series) if series else None
        comparison = compare_page_offer(
            basis=basis,
            comparable_past_price=comparable_avg,
            page_price=price,
            parsed_size=parsed_size,
        )

        matches.append(
            {
                "item_id": item.id,
                "name": item.name or "",
                "confidence": int(entry["confidence"]),
                "matched_by": entry["matched_by"],
                "unit": basis if basis != "each" else None,
                "basis": basis,
                "basis_label": basis_label,
                "last_paid": last_paid,
                "at_this_store": at_this_store,
                "all_stores": all_stores,
                "history": history,
                "comparison": comparison,
            }
        )

    return {
        "query": q,
        "cleaned_query": cleaned_q,
        "store": canonical_store,
        "matches": matches,
    }
