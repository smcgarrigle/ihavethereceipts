import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pdfplumber

logger = logging.getLogger(__name__)

_OCR_FILTERS_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "ocr_filters.json"
)

_FALLBACK_SKIP = [
    "Purchased at",
    "Order Summary",
    "Order Details",
    "Item(s) Subtotal",
    "Shipping",
    "Total before tax",
    "Estimated tax",
    "Grand Total",
    "PAGE",
    "Order placed",
    "Order #",
    "PICKUP AT",
    "Payment method",
]
_FALLBACK_JUNK = [
    r", Non-GMO",
    r", Gluten-Free",
    r", with Immune Support",
    r", Award Winning",
]


# Money as printed on a receipt. The thousands separator matters: the earlier
# [0-9.]+ stopped at the comma in "$1,024.99" and yielded "1", so a four-figure
# order was stored as $1.00. MONEY_CENTS is the anchored form, for lines that
# are only a price.
MONEY = r"[0-9][0-9,]*(?:\.[0-9]+)?"
MONEY_CENTS = r"[0-9][0-9,]*\.[0-9]{2}"

# A parsed total is rejected when the line items sum to more than this multiple
# of it. Generous on purpose: the heuristic line-item loops can over-collect,
# and every instance of the separator bug is off by a factor of ten or more.
_TOTAL_DIVERGENCE_RATIO = 3.0
_TOTAL_DIVERGENCE_FLOOR = 5.0


def _money(raw: str) -> float:
    """Parse a printed money amount, tolerating thousands separators."""
    return float(raw.replace(",", ""))


def _total_is_credible(result: dict[str, Any]) -> bool:
    """Check the parsed total against the sum of the line items.

    A fast-path result that claims a total far below what its own items add up
    to has misread the total, so it is better to fall back to the model than to
    store the wrong number. Items summing to *less* than the total is ordinary
    (a fee or tax line that never parsed), so only the one direction rejects.
    """
    total = result.get("total_amount") or 0.0
    item_sum = sum(float(i.get("final_price") or 0) for i in result.get("items", []))

    if item_sum <= 0:
        return True
    if total <= 0:
        logger.warning(
            f"Fast-Path Parser: items sum to ${item_sum:.2f} but no total was parsed — "
            "falling back to the model"
        )
        return False
    if item_sum - total > _TOTAL_DIVERGENCE_FLOOR and item_sum > total * _TOTAL_DIVERGENCE_RATIO:
        logger.warning(
            f"Fast-Path Parser: items sum to ${item_sum:.2f} but the parsed total is "
            f"${total:.2f} — rejecting the fast path and falling back to the model"
        )
        return False
    return True


def _load_ocr_filters() -> tuple[list[str], list[str]]:
    """Load skip_keywords and junk_filters from ocr_filters.json. ~0.1ms overhead."""
    try:
        with open(_OCR_FILTERS_PATH) as f:
            data = json.load(f)
        return data.get("skip_keywords", _FALLBACK_SKIP), data.get("junk_filters", _FALLBACK_JUNK)
    except Exception:
        return _FALLBACK_SKIP, _FALLBACK_JUNK


def parse_pdf_receipt(pdf_path: str) -> dict[str, Any] | None:
    """
    Fast-Path extraction for digital receipts (Amazon, iHerb, etc.) using pdfplumber.
    Returns a standardized dictionary if successful, or None if it's a scanned PDF (no text).
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            # Concatenate all pages
            full_text = "\n".join(page.extract_text() for page in pdf.pages if page.extract_text())

        if not full_text.strip():
            logger.info(f"Probable scanned PDF (no text found): {pdf_path}")
            return None

        result: dict[str, Any] = {
            "order_number": None,
            "purchase_date": None,
            "total_amount": 0.0,
            "store_name": "Unknown Store",
            "items": [],
            "source": "pdf_parser_fast",
        }

        # -----------------------------------------------------------------------
        # iHerb Pattern
        # -----------------------------------------------------------------------
        if "iHerb" in full_text:
            result["store_name"] = "IHerb"

            # Order metadata
            if m := re.search(r"Order (?:#|Number:)\s*(\d+)", full_text, re.IGNORECASE):
                result["order_number"] = m.group(1)

            if m := re.search(
                r"(?:Placed on |Date of Order: )\s*([A-Za-z]+ \d{1,2},? \d{4})",
                full_text,
                re.IGNORECASE,
            ):
                try:
                    date_str = m.group(1).replace(",", "").strip()
                    dt = datetime.strptime(date_str, "%B %d %Y")
                    result["purchase_date"] = dt.strftime("%Y-%m-%d")
                except Exception:
                    pass

            if m := re.search(rf"Order total\s+\$({MONEY})", full_text, re.IGNORECASE):
                result["total_amount"] = _money(m.group(1))

            # Capturing Fees (Tax, Shipping)
            for m in re.finditer(
                rf"(Tax|Shipping|Handling|Shipping & Handling|S&H)\s+\$({MONEY})",
                full_text,
                re.IGNORECASE,
            ):
                fee_name = m.group(1)
                fee_price = _money(m.group(2))
                if fee_price > 0:  # Only add if it's a real fee
                    result["items"].append(
                        {
                            "name": fee_name,
                            "unit_price": fee_price,
                            "quantity": 1,
                            "final_price": fee_price,
                            "base_price": fee_price,
                            "category": "Fees & Taxes",
                        }
                    )

            # Line items format 1 (Browser UI)
            item_pattern = re.compile(
                rf"([\w].*?)\nUnit price: \$({MONEY}).*?\nQuantity: (\d+)\nItem total: \$({MONEY})",
                re.DOTALL,
            )
            for m in item_pattern.finditer(full_text):
                raw_name = m.group(1).replace("\n", " ").strip()
                # Remove iHerb UI junk
                name = re.sub(
                    r"Payment method.*?Visa x\d{4}\s+\$\d+\.\d+", "", raw_name, flags=re.IGNORECASE
                )
                name = re.sub(r"Rewards\s+\$\d+\.\d+", "", name, flags=re.IGNORECASE)

                # Header Filter: Skip if name looks like a table header
                if "# Item Price" in name or "Quantity" in name:
                    continue

                result["items"].append(
                    {
                        "name": name.strip(" ,"),
                        "unit_price": _money(m.group(2)),
                        "quantity": int(m.group(3)),
                        "final_price": _money(m.group(4)),
                        "base_price": _money(m.group(4)),
                        "category": "Other",
                    }
                )

            # Line items format 2 (Invoice Table / Formal Invoice)
            if "Date of Order:" in full_text:
                # This pattern matches the iHerb invoice table rows.
                # It anchors to the end of the line to ensure we grab the final Subtotal.
                # Columns: $Price Qty [$Discount] $Subtotal
                table_pattern = re.compile(
                    rf"(\$({MONEY})\s+(\d+)\s+(?:-?\${MONEY}\s+)?\$({MONEY}))\s*$"
                )
                lines = full_text.split("\n")
                for i, line in enumerate(lines):
                    m = table_pattern.search(line)
                    if m:
                        price = _money(m.group(2))
                        qty = int(m.group(3))
                        total = _money(m.group(4))

                        # Search backwards for a name (up to 5 lines)
                        name = "Unknown Item"
                        for j in range(i, i - 6, -1):
                            if j < 0:
                                break
                            candidate = lines[j].strip()
                            # Strip the matched price part if on same line
                            candidate = candidate.replace(m.group(1), "").strip()
                            # Strip leading numbers (index)
                            candidate = re.sub(r"^\d+\s+", "", candidate)

                            # Valid name check: No $ sign, not a header, not empty
                            if candidate and len(candidate) > 5 and "$" not in candidate:
                                if not any(
                                    h in candidate
                                    for h in [
                                        "# Item Price",
                                        "Subtotal",
                                        "Discount",
                                        "Total Amount",
                                    ]
                                ):
                                    name = candidate
                                    break

                        if name == "Unknown Item" and total == 0:
                            continue  # Skip unknown items with $0 price

                        result["items"].append(
                            {
                                "name": name,
                                "unit_price": price,
                                "quantity": qty,
                                "final_price": total,
                                "base_price": total,
                                "category": "Other",
                            }
                        )

        elif "Amazon" in full_text or "Order Details" in full_text:
            full_text_lower = full_text.lower()
            if any(
                term in full_text_lower
                for term in ["whole foods", "wholefoods", "450 rhode island", "potrero hill"]
            ):
                result["store_name"] = "Whole Foods Market"
            elif "amazon fresh" in full_text_lower:
                result["store_name"] = "Amazon Fresh"
            else:
                result["store_name"] = "Amazon.com"

            # Order ID
            if m := re.search(r"Order #?:?\s*(\d{3}-\d{7}-\d{7})", full_text, re.IGNORECASE):
                result["order_number"] = m.group(1)

            # Purchase Date
            # e.g., Order placed March 4, 2026 OR Order Date: January 17, 2024
            if m := re.search(
                r"Order (?:placed|Date:?|Ordered)\s*([A-Za-z]+ \d{1,2},? \d{4})",
                full_text,
                re.IGNORECASE,
            ):
                try:
                    date_str = m.group(1).replace(",", "").strip()
                    dt = datetime.strptime(date_str, "%B %d %Y")
                    result["purchase_date"] = dt.strftime("%Y-%m-%d")
                except Exception:
                    pass

            # Total Amount
            m_total = re.search(rf"(?:Grand|Order) Total:\s+\$({MONEY})", full_text, re.IGNORECASE)
            if m_total:
                result["total_amount"] = _money(m_total.group(1))

            lines = full_text.split("\n")
            current_name_parts: list[str] = []
            raw_items: list[dict[str, Any]] = []

            skip_keywords, junk_filters = _load_ocr_filters()

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                # Skip metadata/headers/footers
                if any(k in line for k in skip_keywords):
                    continue
                if "--- PAGE" in line or "©" in line or "Conditions of Use" in line:
                    continue

                # Case A: Line is ONLY a price (e.g. "$4.99")
                price_match = re.match(rf"^\$({MONEY_CENTS})$", line)
                if price_match:
                    price = _money(price_match.group(1))
                    name = " ".join(current_name_parts).strip()
                    # Clean up
                    name = re.sub(r"^(?:collected|collected:)\s+", "", name, flags=re.IGNORECASE)
                    if name:
                        name_lower = name.lower()
                        # Identify if this is a fee/tax
                        is_fee = any(
                            x in name_lower for x in ["tax", "shipping", "handling", "tip"]
                        )
                        # Apply junk filters
                        for filt in junk_filters:
                            name = re.sub(filt, "", name, flags=re.IGNORECASE)

                        # Skip if it's a zero-value fee/tax
                        if is_fee and price == 0:
                            current_name_parts = []
                            continue

                        raw_items.append(
                            {
                                "name": name.strip(" ,"),
                                "unit_price": price,
                                "quantity": 1,
                                "final_price": price,
                                "base_price": price,
                                "category": "Fees & Taxes" if is_fee else "Other",
                            }
                        )
                        current_name_parts = []
                    continue

                # Case B: Line is Name + Price (e.g. "Banana $2.77")
                name_price_match = re.match(rf"^(.*?)\s+\$({MONEY_CENTS})$", line)
                if name_price_match:
                    name_part = name_price_match.group(1).strip()
                    price = _money(name_price_match.group(2))

                    name = " ".join(current_name_parts + [name_part]).strip()
                    name = re.sub(r"^(?:collected|collected:)\s+", "", name, flags=re.IGNORECASE)

                    name_lower = name.lower()
                    is_fee = any(x in name_lower for x in ["tax", "shipping", "handling", "tip"])
                    for filt in junk_filters:
                        name = re.sub(filt, "", name, flags=re.IGNORECASE)

                    # Skip if it's a zero-value fee/tax
                    if is_fee and price == 0:
                        current_name_parts = []
                        continue

                    raw_items.append(
                        {
                            "name": name.strip(" ,"),
                            "unit_price": price,
                            "quantity": 1,
                            "final_price": price,
                            "base_price": price,
                            "category": "Fees & Taxes" if is_fee else "Other",
                        }
                    )
                    current_name_parts = []
                    continue

                # Case C: It's a name fragment
                # Basic check to avoid weird short fragments that look like trash
                if len(line) > 1:
                    current_name_parts.append(line)

            # Filter out garbage items with absurdly long names (recommendation sections)
            result["items"] = [item for item in raw_items if len(str(item.get("name", ""))) <= 150]

        # Final check: an order number means the layout was recognised, but the
        # numbers still have to agree with each other before we trust them.
        if result["order_number"]:
            if not _total_is_credible(result):
                return None
            logger.info(f"Fast-Path Parser: Success for Order {result['order_number']}")
            return result

        return None

    except Exception as e:
        logger.error(f"Error parsing PDF with pdfplumber: {e}")
        return None
