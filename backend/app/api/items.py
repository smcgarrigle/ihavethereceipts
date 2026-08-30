import html as html_mod
import logging

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.database import get_db
from app.models import Item, ReceiptItem
from app.services.spend import LINE_TOTAL

router = APIRouter()
logger = logging.getLogger(__name__)


class UpdateItemRequest(BaseModel):
    name: str | None = None
    category_id: int | None = None

    from pydantic import field_validator

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("Item name must not be empty")
        return v.strip() if v is not None else None


@router.get("/list", response_class=HTMLResponse)
def list_items(category_id: int | None = None, db: Session = Depends(get_db)):
    """List all items with stats, optionally filtered by category"""

    # Base query
    query = db.query(
        Item,
        func.count(ReceiptItem.id).label("purchase_count"),
        func.avg(ReceiptItem.price).label("avg_price"),
        func.sum(LINE_TOTAL).label("total_spent"),
        func.min(ReceiptItem.price).label("min_price"),
        func.max(ReceiptItem.price).label("max_price"),
    ).outerjoin(ReceiptItem, Item.id == ReceiptItem.item_id)

    # Filter by category if provided
    if category_id:
        query = query.filter(Item.category_id == category_id)

    # Filter out administrative noise
    query = query.filter(Item.name != "CUSTOMER SERVICES Bag Refund")

    items_query = query.group_by(Item.id).order_by(func.count(ReceiptItem.id).desc()).all()

    # Sort: CRV items to the bottom, maintain purchase count order for others
    items_query = sorted(items_query, key=lambda x: 1 if "CRV" in (x[0].name or "").upper() else 0)

    if not items_query:
        return """
        <div class="text-center py-12 text-gray-500 dark:text-gray-400">
            <p class="text-lg font-medium">No items in this category yet</p>
        </div>
        """

    # Get all categories for the dropdown
    from app.models import Category, Receipt, Store

    all_categories = db.query(Category).order_by(Category.name).all()

    # --- Pre-fetch logic to avoid N+1 queries ---
    item_ids = [row[0].id for row in items_query if row[1] > 0]

    # Map containers
    receipt_items_map = {}
    store_prices_map = {}

    if item_ids:
        # 1. Batch fetch receipt items for normalized price calculation
        batch_receipt_items = (
            db.query(ReceiptItem)
            .filter(
                ReceiptItem.item_id.in_(item_ids),
                ReceiptItem.unit_price.isnot(None),
                ReceiptItem.unit_type.isnot(None),
            )
            .order_by(ReceiptItem.id.desc())
            .all()
        )

        for ri in batch_receipt_items:
            if ri.item_id not in receipt_items_map:
                receipt_items_map[ri.item_id] = []
            if len(receipt_items_map[ri.item_id]) < 20:
                receipt_items_map[ri.item_id].append(ri)

        # 2. Batch fetch lowest prices per store for all items
        from sqlalchemy import String, cast

        is_sqlite = db.bind.dialect.name == "sqlite"
        agg_func = (
            func.group_concat(Receipt.id)
            if is_sqlite
            else func.string_agg(cast(Receipt.id, String), ",")
        )

        batch_store_prices = (
            db.query(
                ReceiptItem.item_id,
                Store.name,
                func.min(ReceiptItem.price).label("lowest_price"),
                agg_func.label("receipt_ids"),
            )
            .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
            .join(Store, Receipt.store_id == Store.id)
            .filter(ReceiptItem.item_id.in_(item_ids))
            .group_by(ReceiptItem.item_id, Store.id, Store.name)
            .order_by(ReceiptItem.item_id, func.min(ReceiptItem.price).asc())
            .all()
        )

        for item_id, s_name, low_p, r_ids in batch_store_prices:
            if item_id not in store_prices_map:
                store_prices_map[item_id] = []
            store_prices_map[item_id].append((s_name, low_p, r_ids))

    html = '<div class="space-y-2">'
    for (
        item,
        purchase_count,
        avg_price,
        total_spent,
        min_price,
        max_price,
    ) in items_query:
        if purchase_count == 0:
            continue

        total_spent = float(total_spent or 0)
        avg_price = float(avg_price or 0)
        min_price = float(min_price or 0)
        max_price = float(max_price or 0)

        # Calculate Normalized Unit Price (using pre-fetched data)
        receipt_items = receipt_items_map.get(item.id, [])

        avg_unit_price_str = ""
        if receipt_items:
            total_norm = 0
            count = 0
            unit_mode = "oz"
            if any(ri.unit_type in ["l", "ml", "cl", "fl_oz", "gal"] for ri in receipt_items):
                unit_mode = "fl oz"

            for ri in receipt_items:
                try:
                    up = float(ri.unit_price)
                    ut = ri.unit_type
                    # Normalize to Price Per oz/fl oz
                    p_norm = 0
                    if unit_mode == "oz":
                        if ut == "lb":
                            p_norm = up / 16.0
                        elif ut == "oz":
                            p_norm = up
                        elif ut == "kg":
                            p_norm = up / 35.274
                        elif ut == "g":
                            p_norm = up * 28.35
                    elif unit_mode == "fl oz":
                        if ut == "l":
                            p_norm = up / 33.814
                        elif ut == "ml":
                            p_norm = up * 29.574
                        elif ut == "fl_oz":
                            p_norm = up
                        elif ut == "gal":
                            p_norm = up / 128.0

                    if p_norm > 0:
                        total_norm += p_norm
                        count += 1
                except Exception as e:
                    logger.error(f"Error normalizing unit price for item {item.id}: {e}")
                    continue

            if count > 0:
                avg = total_norm / count
                avg_unit_price_str = f"${avg:.2f}/{unit_mode}"

        # Get store prices for this item (lowest price per store) (using pre-fetched data)
        store_prices = store_prices_map.get(item.id, [])

        # Build store price pills
        store_pills = ""
        if store_prices:
            for store_name, lowest_price, receipt_ids in store_prices:
                # Color coding: green for lowest, blue for others
                if lowest_price == store_prices[0][1]:  # Lowest price
                    pill_color = "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 border-green-300 dark:border-green-700 font-bold ring-1 ring-green-500"
                    badge_text = "BEST PRICE"
                else:
                    pill_color = "bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 border-blue-300 dark:border-blue-700"
                    badge_text = ""

                # Filter out nulls and dups from receipt_ids string if SQLite allowed non-distinct concat
                clean_ids = ",".join(list(set(receipt_ids.split(","))))

                store_pills += f"""
                <span class='inline-flex items-center px-2 py-1 text-xs font-medium rounded-full border cursor-pointer hover:shadow-sm transition {pill_color}'
                      role="button" tabindex="0"
                      @click="$dispatch('open-relevant-receipts', {{ids: '{clean_ids}'}})"
                      @keydown.enter="$dispatch('open-relevant-receipts', {{ids: '{clean_ids}'}})"
                      @keydown.space.prevent="$dispatch('open-relevant-receipts', {{ids: '{clean_ids}'}})">
                    {html_mod.escape(store_name)} ${lowest_price:.2f} {f"<span class='ml-1 text-[10px] uppercase opacity-75'>({badge_text})</span>" if badge_text else ""}
                </span>
                """

        # Category pill doubles as the editor: a styled <select> that PATCHes
        # the item in place (no page reload, no separate edit form)
        cat_pill_cls = (
            "text-xs bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300"
            if item.category
            else "text-xs bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400"
        )

        # Show FDC/GTIN badges
        fdc_badge = (
            f"<span class='text-[10px] bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 px-1.5 py-0.5 rounded border border-blue-100 dark:border-blue-800' title='USDA FDC ID'>FDC:{item.fdc_id}</span>"
            if item.fdc_id
            else ""
        )
        gtin_badge = (
            f"<span class='text-[10px] bg-purple-50 dark:bg-purple-900/20 text-purple-600 dark:text-purple-400 px-1.5 py-0.5 rounded border border-purple-100 dark:border-purple-800' title='GTIN/UPC'>UPC:{item.gtin}</span>"
            if item.gtin
            else ""
        )

        # Build category options for dropdown
        category_options = "<option value=''>Uncategorized</option>"
        for cat in all_categories:
            selected = "selected" if item.category_id == cat.id else ""
            category_options += (
                f"<option value='{cat.id}' {selected}>{html_mod.escape(cat.name)}</option>"
            )

        escaped_item_name = html_mod.escape(item.name)
        escaped_name = escaped_item_name.replace("'", "\\'")

        html += f"""
        <div class='bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-sm hover:shadow-md transition overflow-hidden'
             x-data='{{expanded: false, categoryId: {item.category_id or "null"}}}'>

            <!-- Header (Always Visible). The expand/collapse control itself lives on the
                 chevron below, not this whole row, since it also wraps a real <a> link
                 (nested interactive controls aren't allowed) -->
            <div @click="expanded = !expanded" class="p-4 flex justify-between items-center cursor-pointer bg-gray-50/50 dark:bg-gray-800/50 hover:bg-gray-100 dark:hover:bg-gray-700/50 transition-colors">
                <div class="flex-1 min-w-0">
                    <h3 class='font-semibold truncate pr-2'>
                        <a href='/items/{item.id}/insights' @click.stop
                           class='text-gray-900 dark:text-white hover:text-blue-600 dark:hover:text-blue-400 transition-colors'
                           title='Open item page'>{escaped_item_name}</a>
                    </h3>
                    <div class="flex items-center space-x-2 text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                        <span>{purchase_count} pur.</span>
                        <span>•</span>
                        <span class="font-medium text-gray-700 dark:text-gray-300">${avg_price:.2f} avg</span>
                    </div>
                </div>
                <div @click.stop="expanded = !expanded" @keydown.enter="expanded = !expanded" @keydown.space.prevent="expanded = !expanded"
                     role="button" tabindex="0" :aria-expanded="expanded" aria-controls="item-details-{item.id}"
                     aria-label="Toggle details for {escaped_item_name}"
                     class="flex-shrink-0 text-right pl-2">
                    <span class="block font-bold text-gray-900 dark:text-white">${total_spent:.0f}</span>
                    <svg class="w-5 h-5 text-gray-400 transform transition-transform duration-200 mx-auto mt-1"
                         :class="expanded ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                    </svg>
                </div>
            </div>

            <!-- Drawer (Collapsible) -->
            <div id="item-details-{item.id}" x-show="expanded" x-collapse class="border-t border-gray-100 dark:border-gray-700">
                <div class="p-4 space-y-4">

                    <!-- Item Details -->
                    <div>
                        <!-- Stats Grid -->
                        <div class="grid grid-cols-2 gap-4 text-sm mb-4">
                             <div>
                                <p class="text-xs text-gray-500 dark:text-gray-400">Unit Price</p>
                                <p class="font-medium text-blue-600 dark:text-blue-400">{avg_unit_price_str if avg_unit_price_str else "N/A"}</p>
                             </div>
                             <div>
                                <p class="text-xs text-gray-500 dark:text-gray-400">Price Range</p>
                                <p class="font-medium text-gray-700 dark:text-gray-300">
                                    {f"${min_price:.2f} - ${max_price:.2f}" if min_price else "—"}
                                </p>
                             </div>
                        </div>

                        <div class="flex justify-between items-center mb-4">
                             <div class="flex items-center space-x-2">
                                 <select x-model='categoryId' @click.stop title='Change category'
                                         @change='fetch("/api/items/{item.id}", {{
                                             method: "PUT",
                                             headers: {{
                                                 "Content-Type": "application/json",
                                                 "X-CSRF-Token": document.querySelector("meta[name=csrf-token]")?.content || ""
                                             }},
                                             body: JSON.stringify({{category_id: categoryId ? parseInt(categoryId) : null}})
                                         }})'
                                         class='{cat_pill_cls} px-2 py-1 rounded border-0 cursor-pointer focus:ring-2 focus:ring-blue-500'>
                                     {category_options}
                                 </select>
                                 {fdc_badge}
                                 {gtin_badge}
                             </div>
                             <!-- Store Pills -->
                             {f"<div class='flex flex-wrap justify-end gap-1.5'>{store_pills}</div>" if store_pills else ""}
                        </div>

                        <!-- Action Buttons -->
                        <div class="grid grid-cols-3 gap-2 pt-2 border-t border-gray-100 dark:border-gray-700">
                             <button onclick="showPriceHistory(this)"
                                     data-item-id="{item.id}"
                                     data-item-name="{escaped_name}"
                                     class="py-2 px-3 bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg text-xs font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-600 flex items-center justify-center transition-all">
                                <svg class="w-3.5 h-3.5 mr-1.5 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z"></path></svg>
                                History
                            </button>

                            <a href="/items/{item.id}/insights"
                               class="py-2 px-3 {"bg-green-600 text-white hover:bg-green-700 shadow-sm" if item.fdc_id else "bg-gray-50 dark:bg-gray-700/50 text-gray-500 dark:text-gray-400 border border-transparent hover:bg-gray-100 dark:hover:bg-gray-600"} rounded-lg text-xs font-bold flex items-center justify-center transition-all uppercase tracking-tight">
                                <svg class="w-3.5 h-3.5 mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"></path></svg>
                                Insights
                            </a>

                            <button @click="autoEnrich({item.id})"
                                    class="py-2 px-3 bg-indigo-50 dark:bg-indigo-900/20 text-indigo-700 dark:text-indigo-400 rounded-lg text-xs font-medium hover:bg-indigo-100 dark:hover:bg-indigo-900/40 border border-transparent flex items-center justify-center transition-all">
                                <svg class="w-3.5 h-3.5 mr-1.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>
                                USDA Match
                            </button>

                        </div>
                    </div>

                </div>
            </div>
        </div>
        """
    html += "</div>"

    return html


@router.put("/{item_id}")
def update_item(item_id: int, update: UpdateItemRequest, db: Session = Depends(get_db)):
    """Update an item name or category"""

    item = db.query(Item).filter(Item.id == item_id).first()

    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if update.name:
        item.name = update.name
        item.normalized_name = update.name.lower().strip()

    if update.category_id is not None:
        item.category_id = update.category_id

    db.commit()

    return {"success": True, "message": "Item updated"}


class UpdateNutritionRequest(BaseModel):
    custom_nutrients: dict | None = None
    nutrition_source: str | None = None


@router.put("/{item_id}/nutrition")
def update_item_nutrition(
    item_id: int, request: UpdateNutritionRequest, db: Session = Depends(get_db)
):
    """Update custom nutritional data for an item"""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if request.custom_nutrients is not None:
        # Merge with existing custom nutrients. Copy into a new dict — mutating
        # the JSON column's own dict in place isn't tracked by SQLAlchemy, so
        # the commit silently persisted nothing.
        current = dict(item.custom_nutrients or {})
        for k, v in request.custom_nutrients.items():
            if v is None or str(v).strip() == "":
                current.pop(k, None)
            else:
                raw_str = str(v).strip()
                try:
                    current[k] = int(raw_str) if raw_str.isdigit() else float(raw_str)
                except ValueError:
                    current[k] = raw_str
        item.custom_nutrients = current
        flag_modified(item, "custom_nutrients")

    if request.nutrition_source:
        item.nutrition_source = request.nutrition_source

    db.commit()
    return {
        "success": True,
        "message": "Nutrition data updated",
        "effective": item.effective_nutrients,
    }


@router.get("/{item_id}/nutrition/search")
def search_nutrition_apis(item_id: int, q: str, db: Session = Depends(get_db)):
    """Search both USDA and OpenFoodFacts for nutrition data"""
    from app.services.external_product import OpenFoodFactsService
    from app.services.fdc_service import fdc_service

    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    results = []

    # 1. Search OpenFoodFacts
    try:
        off_results = OpenFoodFactsService.search_product(q, limit=5)
        for r in off_results:
            results.append(
                {
                    "source": "off",
                    "id": r["code"],
                    "name": f"{r.get('brand', '')} {r.get('product_name', '')}".strip(),
                    "details": f"Score: {r.get('nutriscore', 'N/A')}",
                    "raw": r,
                }
            )
    except Exception as e:
        logger.error(f"OFF search error: {e}")

    # 2. Search USDA Foundation Foods
    try:
        usda_results = fdc_service.search_items(q)
        if usda_results and "foods" in usda_results:
            for f in usda_results["foods"][:5]:
                results.append(
                    {
                        "source": "usda",
                        "id": f.get("fdcId"),
                        "name": f.get("description", ""),
                        "details": f.get("foodCategory", ""),
                        "raw": f,
                    }
                )
    except Exception as e:
        logger.error(f"USDA search error: {e}")

    return {"success": True, "results": results}


@router.get("/search", response_class=HTMLResponse)
def search_items(q: str = "", db: Session = Depends(get_db)):
    """Search items by name"""
    from sqlalchemy import func

    from app.models import Receipt, Store

    if not q or len(q) < 2:
        return "<p class='text-gray-500 dark:text-gray-400 text-sm'>Type at least 2 characters to search...</p>"

    # Cap search query length to avoid performance degradation on large datasets
    if len(q) > 100:
        q = q[:100]

    # Search for items matching the query
    items = db.query(Item).filter(Item.name.ilike(f"%{q}%")).limit(20).all()

    if not items:
        return "<p class='text-gray-500 dark:text-gray-400 text-sm'>No items found</p>"

    # Get purchase counts
    from app.models import ReceiptItem

    html = """
    <div x-data="{ selectedItems: [], keepItemId: null }">
        <!-- Merge Controls -->
        <div x-show="selectedItems.length > 0" class="mb-4 p-3 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700 rounded-lg">
            <p class="text-sm font-medium text-blue-800 dark:text-blue-400 mb-2">
                <span x-text="selectedItems.length"></span> item(s) selected
            </p>
            <p class="text-xs text-blue-700 dark:text-blue-300 mb-2">
                Select one to KEEP (radio button), then merge the rest
            </p>
            <button
                @click="
                    if (!keepItemId) {
                        alert('Please select an item to keep (radio button)');
                        return;
                    }
                    if (selectedItems.length < 2) {
                        alert('Select at least 2 items to merge');
                        return;
                    }
                    const mergeIds = selectedItems.filter(id => id != keepItemId);
                    if (mergeIds.length === 0) {
                        alert('Select other items to merge into the kept item');
                        return;
                    }
                    if (confirm('Merge ' + mergeIds.length + ' item(s)? This cannot be undone.')) {
                        fetch('/api/items/merge', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'X-CSRF-Token': document.querySelector('meta[name=csrf-token]')?.content || ''
                            },
                            body: JSON.stringify({
                                keep_item_id: parseInt(keepItemId),
                                merge_item_ids: mergeIds.map(id => parseInt(id))
                            })
                        })
                        .then(r => r.json())
                        .then(data => {
                            alert(data.message);
                            selectedItems = [];
                            keepItemId = null;
                            location.reload();
                        })
                        .catch(err => alert('Error: ' + err));
                    }
                "
                class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium">
                Merge Selected Items
            </button>
            <button
                @click="
                    if (confirm('Undo the last merge operation? This will recreate the source item and move its history back.')) {
                        fetch('/api/items/merge/undo', {
                            method: 'POST',
                            headers: {
                                'X-CSRF-Token': document.querySelector('meta[name=csrf-token]')?.content || ''
                            }
                        })
                        .then(r => r.json())
                        .then(data => {
                            alert(data.message);
                            location.reload();
                        })
                        .catch(err => alert('Error: ' + err));
                    }
                "
                class="ml-2 px-4 py-2 bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-300 dark:hover:bg-gray-600 text-sm font-medium">
                Undo Last Merge
            </button>
        </div>

        <!-- Search Results -->
        <div class='space-y-1'>
    """

    for item in items:
        # Get detailed purchase stats
        stats = (
            db.query(
                func.count(ReceiptItem.id).label("count"),
                func.min(Receipt.purchase_date).label("first_date"),
                func.max(Receipt.purchase_date).label("last_date"),
            )
            .join(Receipt)
            .filter(ReceiptItem.item_id == item.id)
            .first()
        )

        purchase_count = stats.count or 0
        date_range = ""
        if stats.first_date and stats.last_date:
            if stats.first_date == stats.last_date:
                date_range = f"on {stats.first_date.strftime('%Y-%m-%d')}"
            else:
                date_range = f"{stats.first_date.strftime('%Y-%m-%d')} to {stats.last_date.strftime('%Y-%m-%d')}"

        # Get most recent store
        last_store = (
            db.query(Store.name)
            .join(Receipt)
            .join(ReceiptItem)
            .filter(ReceiptItem.item_id == item.id)
            .order_by(Receipt.purchase_date.desc())
            .first()
        )
        store_info = f" • Last at {last_store[0]}" if last_store else ""

        category_name = item.category.name if item.category else "Uncategorized"

        html += f"""
        <label class='flex items-center space-x-3 px-3 py-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded cursor-pointer'>
            <!-- Radio for KEEP -->
            <input type='radio'
                   name='keep-item'
                   value='{item.id}'
                   x-model='keepItemId'
                   class='w-4 h-4 text-blue-600'>

            <!-- Item Info -->
            <div class='flex-1'>
                <p class='font-medium text-gray-900 dark:text-white'>{html_mod.escape(item.name)}</p>
                <div class='flex flex-wrap items-center gap-x-2 text-xs text-gray-500 dark:text-gray-400'>
                    <span class='px-1.5 py-0.5 bg-gray-100 dark:bg-gray-600 rounded'>{html_mod.escape(category_name)}</span>
                    <span>{purchase_count} purchases</span>
                    {f"<span>• {date_range}</span>" if date_range else ""}
                    {store_info}
                </div>
            </div>

            <!-- Checkbox for MERGE -->
            <input type='checkbox'
                   value='{item.id}'
                   x-model='selectedItems'
                   class='w-4 h-4 text-green-600'>
        </label>
        """

    html += """
        </div>
    </div>
    """

    return html


@router.get("/duplicates", response_class=HTMLResponse)
def list_duplicates(db: Session = Depends(get_db)):
    """Find potential duplicate items based on similar names using rapidfuzz"""
    from rapidfuzz import fuzz

    all_items = db.query(Item).all()
    if not all_items:
        return ""

    # Get ignored matches
    from app.models.item import ItemMatchIgnore

    ignored_pairs = set()
    ignored_records = db.query(ItemMatchIgnore).all()
    for record in ignored_records:
        ignored_pairs.add(tuple(sorted([record.item_id_1, record.item_id_2])))

    seen = set()
    duplicates = []

    for i, item1 in enumerate(all_items):
        if item1.id in seen:
            continue

        similar_items = [item1]
        for item2 in all_items[i + 1 :]:
            if item2.id in seen:
                continue

            # Check if pair is ignored
            pair = tuple(sorted([item1.id, item2.id]))
            if pair in ignored_pairs:
                continue

            # Use rapidfuzz token_sort_ratio for better accuracy
            score = fuzz.token_sort_ratio(item1.normalized_name, item2.normalized_name)

            if score >= 85:  # High confidence threshold
                similar_items.append(item2)

        if len(similar_items) > 1:
            for it in similar_items:
                seen.add(it.id)
            duplicates.append(similar_items)

    if not duplicates:
        return """
        <div class='text-center py-8'>
            <p class='text-gray-500 dark:text-gray-400'>✓ No potential duplicates found!</p>
        </div>
        """

    html = '<div class="space-y-4">'
    for group in duplicates:
        card_id = f"dup-group-{group[0].id}"
        id1 = group[0].id
        id2 = group[1].id

        html += f"<div id='{card_id}' class='p-4 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg relative group'>"

        # Dismiss Button
        html += f"""
        <button
            hx-post="/api/items/duplicates/ignore"
            hx-vals='{{"item_id_1": {id1}, "item_id_2": {id2}}}'
            hx-target="closest div"
            hx-swap="outerHTML"
            class="absolute top-2 right-2 text-yellow-600 dark:text-yellow-500 hover:text-yellow-800 dark:hover:text-yellow-300 opacity-0 group-hover:opacity-100 transition-opacity p-1"
            title="Dismiss this match">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
        </button>
        """

        html += "<p class='text-sm font-medium text-yellow-800 dark:text-yellow-400 mb-2'>Possible duplicates:</p>"
        html += "<ul class='space-y-1'>"
        for item in group:
            html += (
                f"<li class='text-sm text-gray-700 dark:text-gray-300'>"
                f"• {html_mod.escape(item.name)}</li>"
            )
        html += "</ul>"
        html += "</div>"
    html += "</div>"
    return html


class IgnoreMatchRequest(BaseModel):
    item_id_1: int
    item_id_2: int


@router.post("/duplicates/ignore")
def ignore_duplicate_match(
    item_id_1: int = Form(...), item_id_2: int = Form(...), db: Session = Depends(get_db)
):
    """Ignore a specific pair of items in duplicate detection"""
    from app.models.item import ItemMatchIgnore

    # Sort IDs to ensure consistency
    ids = sorted([item_id_1, item_id_2])

    # Check if already exists
    existing = (
        db.query(ItemMatchIgnore)
        .filter(ItemMatchIgnore.item_id_1 == ids[0], ItemMatchIgnore.item_id_2 == ids[1])
        .first()
    )

    if not existing:
        ignore = ItemMatchIgnore(item_id_1=ids[0], item_id_2=ids[1])
        db.add(ignore)
        db.commit()

    return {"success": True}


@router.get("/ignored-suggestions", response_class=HTMLResponse)
def list_ignored_suggestions(db: Session = Depends(get_db)):
    """List all ignored duplicate suggestions for management"""
    from app.models.item import Item, ItemMatchIgnore

    ignored = db.query(ItemMatchIgnore).all()
    if not ignored:
        return "<p class='text-gray-500 dark:text-gray-400 text-sm p-4'>No ignored suggestions found.</p>"

    # Batch fetch all potential items to avoid N+1 queries
    all_item_ids = set()
    for record in ignored:
        all_item_ids.add(record.item_id_1)
        all_item_ids.add(record.item_id_2)

    items_map = {item.id: item for item in db.query(Item).filter(Item.id.in_(all_item_ids)).all()}

    html = "<div class='divide-y divide-gray-200 dark:divide-gray-700'>"
    for record in ignored:
        item1 = items_map.get(record.item_id_1)
        item2 = items_map.get(record.item_id_2)

        if not item1 or not item2:
            continue

        html += f"""
        <div class='flex items-center justify-between p-3 hover:bg-gray-50 dark:hover:bg-gray-700/50'>
            <div class='text-sm'>
                <span class='font-medium text-gray-900 dark:text-white'>{html_mod.escape(item1.name)}</span>
                <span class='text-gray-400 mx-2'>≠</span>
                <span class='font-medium text-gray-900 dark:text-white'>{html_mod.escape(item2.name)}</span>
            </div>
            <button hx-delete="/api/items/ignored-suggestions/{record.id}"
                    hx-confirm="Show suggestions for this pair again?"
                    hx-target="closest div"
                    hx-swap="outerHTML"
                    class='text-xs text-red-600 hover:text-red-800 dark:text-red-400 dark:hover:text-red-300 font-medium'>
                Restore
            </button>
        </div>
        """
    html += "</div>"
    return html


@router.delete("/ignored-suggestions/{ignore_id}")
def delete_ignored_suggestion(ignore_id: int, db: Session = Depends(get_db)):
    """Remove an ignore record so the suggestion can appear again"""
    from app.models.item import ItemMatchIgnore

    record = db.query(ItemMatchIgnore).filter(ItemMatchIgnore.id == ignore_id).first()
    if record:
        db.delete(record)
        db.commit()
    return HTMLResponse("")


class MergeItemsRequest(BaseModel):
    keep_item_id: int
    merge_item_ids: list[int]


@router.post("/merge")
def merge_items(request: MergeItemsRequest, db: Session = Depends(get_db)):
    """Merge multiple items into one, preserving all receipt data"""
    import json

    from app.models import MergeLog, ReceiptItem

    try:
        target_item = db.query(Item).filter(Item.id == request.keep_item_id).first()
        if not target_item:
            raise HTTPException(status_code=404, detail="Target item not found")

        merged_count = 0
        # We manually manage the transaction to ensure atomicity across all merges in the request
        for source_id in request.merge_item_ids:
            if source_id == request.keep_item_id:
                continue

            source_item = db.query(Item).filter(Item.id == source_id).first()
            if not source_item:
                continue

            # Record affected receipt items for undo
            receipt_items = db.query(ReceiptItem).filter(ReceiptItem.item_id == source_id).all()
            receipt_item_ids = [ri.id for ri in receipt_items]

            # Reassign all receipt items
            db.query(ReceiptItem).filter(ReceiptItem.item_id == source_id).update(
                {"item_id": request.keep_item_id}, synchronize_session=False
            )

            # Log the merge
            log = MergeLog(
                target_item_id=request.keep_item_id,
                source_item_name=source_item.name,
                source_item_category_id=source_item.category_id,
                receipt_item_ids=json.dumps(receipt_item_ids),
            )
            db.add(log)

            # Delete source item
            db.delete(source_item)
            merged_count += 1

        db.commit()
        return {
            "success": True,
            "message": f"Merged {merged_count} items into '{target_item.name}'",
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Merge failed: {str(e)}") from e


@router.post("/merge/undo")
def undo_merge(db: Session = Depends(get_db)):
    """Undo the very last merge operation"""
    import json

    from app.models import MergeLog, ReceiptItem

    # Find the most recent merge log
    log = db.query(MergeLog).order_by(MergeLog.merged_at.desc()).first()
    if not log:
        raise HTTPException(status_code=404, detail="No merge history found to undo")

    try:
        # 1. Recreate the source item
        source_item = Item(
            name=log.source_item_name,
            normalized_name=log.source_item_name.lower().strip(),
            category_id=log.source_item_category_id,
        )
        db.add(source_item)
        db.flush()  # Get source_item.id

        # 2. Reassign receipt items back to source
        receipt_item_ids = json.loads(log.receipt_item_ids)
        if receipt_item_ids:
            db.query(ReceiptItem).filter(ReceiptItem.id.in_(receipt_item_ids)).update(
                {"item_id": source_item.id}, synchronize_session=False
            )

        # 3. Delete the log
        db.delete(log)
        db.commit()

        return {
            "success": True,
            "message": f"Undid merge of '{log.source_item_name}' into item {log.target_item_id}",
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Undo failed: {str(e)}") from e


@router.get("/external/search")
def search_external_product(q: str):
    """Search OpenFoodFacts for product metadata"""
    from app.services.external_product import OpenFoodFactsService

    if not q or len(q) < 3:
        return []

    return OpenFoodFactsService.search_product(q)


@router.get("/fdc/search")
def search_fdc_product(q: str):
    """Search USDA FDC for product metadata"""
    from app.services.fdc_service import fdc_service

    if not q or len(q) < 3:
        return []

    return fdc_service.search_items(q)


@router.post("/{item_id}/enrich")
def enrich_item_fdc(item_id: int, db: Session = Depends(get_db)):
    """Trigger FDC enrichment for a specific item.

    Respects the global USDA lookup feature flag — returns a disabled response
    when the toggle is off without erasing any existing nutritional data.
    """
    import json
    from pathlib import Path

    flags_path = (
        Path(__file__).resolve().parent.parent.parent.parent / "data" / "feature_flags.json"
    )
    try:
        flags = json.loads(flags_path.read_text())
    except Exception:
        flags = {}

    if not flags.get("usda_lookup_enabled", True):
        return {
            "success": False,
            "disabled": True,
            "message": "USDA lookups are currently paused. Re-enable them in Settings → Exclusions Manager.",
        }

    from app.services.fdc_service import fdc_service

    success = fdc_service.enrich_db_item(db, item_id)
    if success:
        return {"success": True, "message": "Item enriched with FDC data"}
    else:
        return {"success": False, "message": "No high-confidence match found in FDC"}


class SetFdcMatchRequest(BaseModel):
    fdc_ref: str


def _parse_fdc_ref(ref: str) -> int | None:
    """Extract an FDC ID from a fdc.nal.usda.gov URL or a bare numeric ID."""
    import re

    ref = ref.strip()
    if re.fullmatch(r"\d{3,10}", ref):
        return int(ref)
    # Handles both URL shapes:
    #   https://fdc.nal.usda.gov/food-details/2003586/nutrients
    #   https://fdc.nal.usda.gov/fdc-app.html#/food-details/2003586/nutrients
    match = re.search(r"food-details/(\d+)", ref)
    if match:
        return int(match.group(1))
    return None


@router.put("/{item_id}/fdc")
def set_item_fdc_match(item_id: int, request: SetFdcMatchRequest, db: Session = Depends(get_db)):
    """Manually pin an item to a specific USDA FDC food (paste a URL or FDC ID).

    Replaces the automatic match, refreshes canonical nutrients from the chosen
    food, and flags the item so auto-enrichment won't overwrite the choice.
    Field-level custom_nutrients edits are preserved and still win.
    """
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    fdc_id = _parse_fdc_ref(request.fdc_ref)
    if not fdc_id:
        raise HTTPException(
            status_code=400,
            detail="Couldn't find an FDC ID in that input. Paste a fdc.nal.usda.gov "
            "food-details URL or the numeric FDC ID itself.",
        )

    from app.services.fdc_service import fdc_service

    food = fdc_service.get_food_details(fdc_id)
    if not food:
        raise HTTPException(
            status_code=502,
            detail=f"USDA FDC returned no data for ID {fdc_id}. "
            "Check the URL, or try again if the API is unavailable.",
        )

    item.fdc_id = fdc_id
    item.fdc_override = True
    item.gtin = food.get("gtinUpc") or item.gtin
    item.ingredients = food.get("ingredients") or None

    # Manual pin is authoritative: replace canonical nutrients with the chosen
    # food's values. Field-level custom_nutrients still override on top.
    nutrients = fdc_service.extract_nutrients_100g(food)
    if nutrients:
        item.nutrients = nutrients

    db.commit()

    description = food.get("description") or f"FDC #{fdc_id}"
    logger.info(f"Manual FDC override for item {item_id} ({item.name}) -> {fdc_id} ({description})")
    return {
        "success": True,
        "fdc_id": fdc_id,
        "description": description,
        "data_type": food.get("dataType"),
        "nutrients_found": len(nutrients),
        "message": f"Matched to {description}",
    }


@router.delete("/{item_id}/fdc")
def clear_item_fdc(item_id: int, db: Session = Depends(get_db)):
    """Clear an incorrect FDC association from an item."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    item.fdc_id = None
    item.fdc_override = False
    item.gtin = None
    item.ingredients = None
    item.nutrients = None
    db.commit()

    logger.info(f"Cleared FDC data for item {item_id} ({item.name})")
    return {"success": True, "message": f"FDC data cleared for '{item.name}'"}


class UpdateItemImageRequest(BaseModel):
    image_url: str


@router.put("/{item_id}/image")
def update_item_image(item_id: int, request: UpdateItemImageRequest, db: Session = Depends(get_db)):
    """Update item image from external URL"""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    import uuid
    from pathlib import Path

    from app.utils.safe_fetch import UnsafeURLError, fetch_remote_image

    try:
        # The extension comes from the response Content-Type, not the URL, so
        # the caller cannot choose what the file is stored as.
        image_bytes, ext = fetch_remote_image(request.image_url)
    except UnsafeURLError as e:
        logger.warning(f"Refused item image fetch for item {item_id}: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to download image: {str(e)}") from e

    try:
        filename = f"item_{item_id}_{uuid.uuid4().hex[:8]}.{ext}"
        # Absolute, so the file lands in the served static dir regardless of
        # the working directory the app was started from.
        save_dir = Path(__file__).resolve().parents[2] / "static" / "uploads"
        save_dir.mkdir(parents=True, exist_ok=True)
        (save_dir / filename).write_bytes(image_bytes)

        # Update DB
        item.image_path = filename
        db.commit()

        return {"success": True, "image_path": filename}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save image: {str(e)}") from e
