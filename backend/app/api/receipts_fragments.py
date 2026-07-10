"""HTMX HTML-fragment endpoints for receipts (list, cards, item rows).

Split out of receipts.py — mounted on the same /api/receipts prefix, so all
route paths are unchanged.
"""

import html
import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Receipt

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/{receipt_id}/items", response_class=HTMLResponse)
def get_receipt_items(receipt_id: int, db: Session = Depends(get_db)):
    """Get items for a specific receipt with edit controls"""

    from app.models import ReceiptItem

    receipt = db.query(Receipt).filter(Receipt.id == receipt_id).first()
    if not receipt:
        return "<p class='text-red-500 dark:text-red-400'>Receipt not found</p>"

    from sqlalchemy.orm import joinedload

    receipt_items = (
        db.query(ReceiptItem)
        .options(joinedload(ReceiptItem.item))
        .filter(ReceiptItem.receipt_id == receipt_id)
        .all()
    )

    if not receipt_items:
        return "<p class='text-gray-500 dark:text-gray-400 text-sm'>No items saved yet. Visit the review page to add items.</p>"

    html_resp = "<div class='space-y-2'>"
    subtotal = 0

    for receipt_item in receipt_items:
        item = receipt_item.item
        if not item:
            continue

        line_total = receipt_item.price * receipt_item.quantity
        subtotal += line_total

        # Parse notes to show discount/fee breakdown
        breakdown_html = ""
        if receipt_item.notes:
            try:
                notes_data = json.loads(receipt_item.notes)
                if "base_price" in notes_data:
                    parts = [f"Base: ${notes_data['base_price']:.2f}"]

                    if notes_data.get("discounts") and len(notes_data["discounts"]) > 0:
                        total_discount = sum(
                            float(d.get("amount", 0)) for d in notes_data["discounts"]
                        )
                        parts.append(f"Disc: -${total_discount:.2f}")

                    if notes_data.get("fees") and len(notes_data["fees"]) > 0:
                        total_fees = sum(float(f.get("amount", 0)) for f in notes_data["fees"])
                        fee_types = ", ".join({f.get("type", "fee") for f in notes_data["fees"]})
                        parts.append(f"{fee_types.upper()}: +${total_fees:.2f}")

                    breakdown_html = f"<p class='text-xs text-gray-500 dark:text-gray-400'>{' • '.join(parts)}</p>"
            except Exception as e:
                logger.error(f"Error parsing notes for receipt_item {receipt_item.id}: {e}")
                pass

        escaped_item_name = html.escape(item.name)
        html_resp += f"""
        <div class='flex justify-between items-center text-sm border-b dark:border-gray-700 pb-2 py-2'
             id='receipt-item-{receipt_item.id}'>
            <div>
                <p class='font-medium text-gray-900 dark:text-white'>{escaped_item_name}</p>
                <p class='text-xs text-gray-500 dark:text-gray-400'>Qty: {receipt_item.quantity}</p>
                {breakdown_html}
            </div>
            <div class='text-right flex items-center space-x-2'>
                <div>
                    <p class='font-semibold text-gray-900 dark:text-white'>${line_total:.2f}</p>
                    <p class='text-xs text-gray-500 dark:text-gray-400'>${receipt_item.price:.2f} each</p>
                </div>
                <button
                    hx-delete='/api/receipts/{receipt_id}/items/{receipt_item.id}'
                    hx-confirm='Delete this item?'
                    hx-target='#receipt-item-{receipt_item.id}'
                    hx-swap='outerHTML'
                    class='px-2 py-1 text-xs bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 rounded hover:bg-red-200 dark:hover:bg-red-900/50'>
                    Delete
                </button>
            </div>
        </div>
        """

    # Total section
    html_resp += f"""
    <div class='flex justify-between items-center font-bold pt-2 text-lg text-gray-900 dark:text-white border-t dark:border-gray-700 mt-2'>
        <span>Total:</span>
        <span>${subtotal:.2f}</span>
    </div>
    """

    html_resp += "</div>"

    return html_resp


def _render_receipt_card_html(
    receipt, item_count: int, display_total: float, is_full_list: bool = True
):
    """
    Unified helper to render a receipt card HTML fragment.
    Used by both the full list and the individual card refresh endpoint.
    """
    import json
    from pathlib import Path

    store_name = html.escape(receipt.store.name) if receipt.store else "Unknown Store"
    date_str = (
        receipt.purchase_date.strftime("%B %d, %Y at %I:%M %p")
        if receipt.purchase_date
        else "Unknown Date"
    )

    # Securely escape strings for JS injection
    image_name_json = json.dumps(
        "/uploads/" + Path(receipt.image_path).name if receipt.image_path else ""
    )
    confirm_msg_json = json.dumps("Delete this receipt? This cannot be undone.")

    ocr_backend = "Unknown"
    ocr_model = ""
    if receipt.ocr_data:
        try:
            ocr_parsed = json.loads(receipt.ocr_data)
            ocr_backend = ocr_parsed.get("ocr_backend", "N/A")
            ocr_model = ocr_parsed.get("ocr_model", "")
        except Exception:
            pass

    backend_badge = ""
    if ocr_backend and ocr_backend != "N/A":
        display_text = f"OCR: {html.escape(str(ocr_backend).title())}"
        if ocr_model:
            display_text += f" ({html.escape(str(ocr_model))})"
        backend_badge = f'<span class="inline-flex items-center rounded-md bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 ring-1 ring-inset ring-blue-700/10 dark:bg-blue-900/30 dark:text-blue-300 dark:ring-blue-400/20 ml-2" title="OCR Backend used">{display_text}</span>'

    # Shared buttons
    view_items_btn = f"""
        <button
            class="px-3 py-1 text-sm bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 rounded hover:bg-blue-200 dark:hover:bg-blue-900/50"
            hx-get="/api/receipts/{receipt.id}/items"
            hx-target="#receipt-items-{receipt.id}"
            hx-swap="innerHTML"
            onclick="this.parentElement.parentElement.parentElement.querySelector('.items-container').classList.toggle('hidden')"
        >View Items</button>
    """

    view_image_btn = ""
    if receipt.image_path:
        view_image_btn = f"""
            <button
                 class="px-3 py-1 text-sm bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400 rounded hover:bg-indigo-200 dark:hover:bg-indigo-900/50"
                 @click='$dispatch("open-image", {image_name_json})'
            >View Image</button>
        """

    if item_count == 0:
        edit_btn = f"""
            <a
                class="px-3 py-1 text-sm bg-gray-100 dark:bg-gray-800 text-amber-600 dark:text-amber-500 font-semibold rounded hover:bg-gray-200 dark:hover:bg-gray-700 no-underline inline-block text-center border border-amber-200 dark:border-amber-900/50"
                style="background-image: repeating-linear-gradient(45deg, transparent, transparent 10px, rgba(245, 158, 11, 0.05) 10px, rgba(245, 158, 11, 0.05) 20px);"
                href="/receipts/{receipt.id}/review"
            >Review Receipt</a>
        """
    else:
        edit_btn = f"""
            <a
                class="px-3 py-1 text-sm bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded hover:bg-gray-200 dark:hover:bg-gray-600 no-underline inline-block text-center"
                href="/receipts/{receipt.id}/review"
            >Edit Receipt</a>
        """

    delete_btn = f"""
        <button
            class="px-3 py-1 text-sm bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 rounded hover:bg-red-200 dark:hover:bg-red-900/50"
            hx-delete="/api/receipts/{receipt.id}"
            hx-confirm='{confirm_msg_json}'
            hx-target="#receipt-{receipt.id}"
            hx-swap="outerHTML"
        >Delete</button>
    """

    export_btn = f"""
        <div class="flex gap-1">
            <a href="/api/export/receipt/{receipt.id}/csv"
               class="flex-1 text-[10px] py-1 bg-gray-50 dark:bg-gray-700/50 text-gray-500 dark:text-gray-400 rounded border border-gray-100 dark:border-gray-600 hover:bg-gray-100 dark:hover:bg-gray-600 transition text-center no-underline font-mono">CSV</a>
            <a href="/api/export/receipt/{receipt.id}/excel"
               class="flex-1 text-[10px] py-1 bg-green-50/50 dark:bg-green-900/10 text-green-600 dark:text-green-500 rounded border border-green-100 dark:border-green-900/30 hover:bg-green-100/50 dark:hover:bg-green-900/20 transition text-center no-underline font-mono">XLSX</a>
        </div>
    """

    new_tab_btn = ""
    if is_full_list:
        new_tab_btn = f"""
            <a
                href="/receipts#receipt-{receipt.id}"
                target="_blank"
                class="px-3 py-1 text-sm bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-400 rounded hover:bg-green-100 dark:hover:bg-green-900/40 no-underline inline-block text-center mt-1"
                title="Open in new tab"
            >
                <svg class="w-4 h-4 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path>
                </svg>
            </a>
        """

    return f"""
    <div class="p-4 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg hover:shadow-md transition"
         id="receipt-{receipt.id}" data-store='{store_name}'>
        <div class="flex justify-between items-start">
            <div class="flex-1">
                <h3 class="font-semibold text-gray-900 dark:text-white">{store_name}</h3>
                <p class="text-sm text-gray-500 dark:text-gray-400 flex items-center">{date_str}{backend_badge}</p>
                <p class="text-lg font-bold text-gray-900 dark:text-white mt-2">${display_total:.2f}</p>
                <p class="text-xs text-gray-500 dark:text-gray-400 mt-1">{item_count} items</p>
            </div>
            <div class="flex flex-col space-y-2">
                {view_items_btn}
                {view_image_btn}
                {edit_btn}
                {delete_btn}
                {export_btn}
                {new_tab_btn}
            </div>
        </div>
        <div id="receipt-items-{receipt.id}" class="items-container mt-4 pt-4 border-t border-gray-200 dark:border-gray-700 hidden"></div>
    </div>
    """


@router.get("/list", response_class=HTMLResponse)
def list_receipts(
    db: Session = Depends(get_db),
    sort: str = "desc",
    ids: str | None = None,
):
    """List all receipts as HTML"""

    from sqlalchemy.orm import joinedload

    query = db.query(Receipt).options(joinedload(Receipt.store), joinedload(Receipt.items))

    if ids:
        try:
            id_list = [int(i.strip()) for i in ids.split(",") if i.strip()]
            if id_list:
                query = query.filter(Receipt.id.in_(id_list))
        except ValueError:
            logger.warning(f"Invalid receipt ID list provided: {ids}")
            pass

    if sort == "asc":
        query = query.order_by(Receipt.purchase_date.asc(), Receipt.created_at.asc())
    else:
        query = query.order_by(Receipt.purchase_date.desc(), Receipt.created_at.desc())

    receipts = query.all()

    if not receipts:
        # Default empty state
        return """
        <div class="text-center py-12 text-gray-500 dark:text-gray-400">
            <svg class="w-16 h-16 mx-auto mb-4 text-gray-300 dark:text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
            </svg>
            <p class="text-lg font-medium">No receipts yet</p>
            <p class="text-sm mt-2">Upload your first receipt to get started</p>
        </div>
        """

    html_resp = '<div class="space-y-3">'
    for receipt in receipts:
        # Items are pre-fetched via joinedload
        receipt_items = receipt.items
        item_count = len(receipt_items)
        actual_total = sum(ri.price * ri.quantity for ri in receipt_items)

        display_total = (
            actual_total if (item_count > 0 and actual_total > 0) else (receipt.total_amount or 0.0)
        )

        html_resp += _render_receipt_card_html(receipt, item_count, display_total)

    html_resp += "</div>"
    return html_resp


@router.get("/{receipt_id}/edit-form", response_class=HTMLResponse)
def get_receipt_edit_form(receipt_id: int, db: Session = Depends(get_db)):
    """Get HTMX edit form for a receipt"""

    receipt = db.query(Receipt).filter(Receipt.id == receipt_id).first()
    if not receipt:
        return ""

    # Pre-format date
    date_val = receipt.purchase_date.strftime("%Y-%m-%d")
    store_val = receipt.store.name

    html_parts = [
        f'<div class="p-4 bg-white dark:bg-gray-800 border border-blue-500 dark:border-blue-400 rounded-lg shadow-md" id="receipt-{receipt.id}">',
        f'    <form hx-patch="/api/receipts/{receipt.id}" hx-target="#receipt-{receipt.id}" hx-swap="outerHTML">',
        '        <div class="space-y-3">',
        "            <div>",
        '                <label class="block text-xs font-medium text-gray-700 dark:text-gray-300">Store Name</label>',
        f'                <input type="text" name="store_name" value="{store_val}"',
        '                       class="mt-1 w-full rounded-md border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-white shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm">',
        "            </div>",
        "            <div>",
        '                <label class="block text-xs font-medium text-gray-700 dark:text-gray-300">Date</label>',
        f'                <input type="date" name="purchase_date" value="{date_val}"',
        '                       class="mt-1 w-full rounded-md border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-white shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm">',
        "            </div>",
        '            <div class="flex justify-end space-x-2 pt-2">',
        '                 <button type="button"',
        f'                        hx-get="/api/receipts/{receipt.id}/card"',
        f'                        hx-target="#receipt-{receipt.id}"',
        '                        hx-swap="outerHTML"',
        '                        class="px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 rounded hover:bg-gray-200 dark:hover:bg-gray-600">',
        "                    Cancel",
        "                </button>",
        '                <button type="submit"',
        '                        class="px-3 py-1.5 text-xs font-medium text-white bg-blue-600 rounded hover:bg-blue-700">',
        "                    Save",
        "                </button>",
        "            </div>",
        "        </div>",
        "    </form>",
        "</div>",
    ]

    return "\n".join(html_parts)


@router.get("/{receipt_id}/card", response_class=HTMLResponse)
def get_receipt_card(receipt_id: int, db: Session = Depends(get_db)):
    """Get read-only receipt card (fragment)"""

    receipt = db.query(Receipt).filter(Receipt.id == receipt_id).first()
    if not receipt:
        return ""

    from sqlalchemy import func

    from app.models import ReceiptItem

    stats = (
        db.query(
            func.count(ReceiptItem.id).label("count"),
            func.sum(ReceiptItem.price * ReceiptItem.quantity).label("total"),
        )
        .filter(ReceiptItem.receipt_id == receipt.id)
        .first()
    )

    item_count = stats.count or 0
    actual_total = float(stats.total or 0.0)

    display_total = actual_total if item_count > 0 else receipt.total_amount

    return _render_receipt_card_html(receipt, item_count, display_total, is_full_list=False)
