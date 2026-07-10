"""Analytics HTML fragments — server-rendered tables, widgets, and drilldowns.

Split from analytics.py; JSON chart-data endpoints remain there. Both routers
are mounted under /api/analytics.
"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Category, Item, Receipt, ReceiptItem, Store

router = APIRouter()


from app.api.analytics import _get_analytics_exclusions, _get_top_items


@router.get("/tables/top-categories", response_class=HTMLResponse)
def get_top_categories_html(limit: int = 8, db: Session = Depends(get_db)):
    """Get HTML table for top categories"""
    results = (
        db.query(
            Category.name,
            func.sum(ReceiptItem.price * ReceiptItem.quantity).label("total"),
        )
        .join(Item, Category.id == Item.category_id)
        .join(ReceiptItem, Item.id == ReceiptItem.item_id)
        .filter(
            Category.name.notin_(
                ["Excluded", "Other", "Fees & Taxes", "CRV (tax)", "Non-Alcoholic Beer"]
            )
        )
        .group_by(Category.id, Category.name)
        .order_by(func.sum(ReceiptItem.price * ReceiptItem.quantity).desc())
        .limit(limit)
        .all()
    )

    html = """
    <div class="overflow-hidden rounded-lg border border-gray-200 dark:border-gray-700">
        <table class="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
            <thead class="bg-gray-50 dark:bg-gray-700/50">
                <tr>
                    <th scope="col" class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Category</th>
                    <th scope="col" class="px-4 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Total</th>
                </tr>
            </thead>
            <tbody class="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
    """

    for name, total in results:
        html += f"""
            <tr>
                <td class="px-4 py-2 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-white truncate max-w-[150px]" title="{name}">{name}</td>
                <td class="px-4 py-2 whitespace-nowrap text-sm text-right text-gray-500 dark:text-gray-400">${total:.2f}</td>
            </tr>
        """

    html += "</tbody></table></div>"
    return html


@router.get("/widgets/category-breakdown", response_class=HTMLResponse)
def get_category_breakdown_widget(db: Session = Depends(get_db)):
    """
    Get a premium Category Breakdown widget for the dashboard (Current Month)
    """
    from dateutil.relativedelta import relativedelta
    from sqlalchemy import func

    from app.models import Category, Item, Receipt, ReceiptItem

    # 1. Setup Dates
    now = datetime.now()
    month_name = now.strftime("%B %Y")
    start_of_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_of_last_month = start_of_this_month - relativedelta(months=1)
    end_of_last_month = start_of_this_month - relativedelta(seconds=1)

    # 2. Get This Month's Stats by Category
    this_month_stats = (
        db.query(
            Category.id,
            Category.name,
            func.sum(ReceiptItem.price * ReceiptItem.quantity).label("total"),
            func.count(func.distinct(ReceiptItem.id)).label("item_count"),
            func.count(func.distinct(Receipt.store_id)).label("store_count"),
        )
        .join(Item, Category.id == Item.category_id)
        .join(ReceiptItem, Item.id == ReceiptItem.item_id)
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .filter(Receipt.purchase_date >= start_of_this_month)
        .filter(
            Category.name.notin_(
                ["Excluded", "Other", "Fees & Taxes", "CRV (tax)", "Non-Alcoholic Beer"]
            )
        )
        .group_by(Category.id, Category.name)
        .all()
    )

    # Calculate total for % share
    total_month_spent = sum(r.total for r in this_month_stats) if this_month_stats else 0

    # 3. Get Last Month's Stats for Comparison
    last_month_stats = (
        db.query(Category.id, func.sum(ReceiptItem.price * ReceiptItem.quantity).label("total"))
        .join(Item, Category.id == Item.category_id)
        .join(ReceiptItem, Item.id == ReceiptItem.item_id)
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .filter(Receipt.purchase_date >= start_of_last_month)
        .filter(Receipt.purchase_date <= end_of_last_month)
        .filter(
            Category.name.notin_(
                ["Excluded", "Other", "Fees & Taxes", "CRV (tax)", "Non-Alcoholic Beer"]
            )
        )
        .group_by(Category.id)
        .all()
    )
    last_month_lookup = {r.id: float(r.total) for r in last_month_stats}

    # 4. Icon & Color Configuration
    config = {
        "Produce": {"icon": "🥦", "color": "bg-green-500", "bg": "bg-green-500/10"},
        "Dairy": {"icon": "🧀", "color": "bg-blue-500", "bg": "bg-blue-500/10"},
        "Meat": {"icon": "🥩", "color": "bg-red-500", "bg": "bg-red-500/10"},
        "Pantry": {"icon": "🥫", "color": "bg-orange-500", "bg": "bg-orange-500/10"},
        "Beverages": {"icon": "☕", "color": "bg-purple-500", "bg": "bg-purple-500/10"},
        "Frozen": {"icon": "❄️", "color": "bg-cyan-500", "bg": "bg-cyan-500/10"},
        "Bakery": {"icon": "🥐", "color": "bg-yellow-500", "bg": "bg-yellow-500/10"},
        "Deli": {"icon": "🥪", "color": "bg-pink-500", "bg": "bg-pink-500/10"},
    }

    # 5. Build HTML
    html = f"""
    <div class="bg-[#1a1a1a] rounded-2xl p-6 shadow-2xl border border-gray-800">
        <div class="mb-6">
            <h2 class="text-xl font-bold text-white mb-1">Category breakdown - {month_name}</h2>
            <p class="text-sm text-gray-400">Tap any category to drill into individual items</p>
        </div>

        <div class="space-y-4">
    """

    # Sort categories by spending (highest first)
    sorted_stats = sorted(this_month_stats, key=lambda x: x.total, reverse=True)

    footer_legend = []

    for row in sorted_stats:
        cat_config = config.get(
            row.name, {"icon": "📦", "color": "bg-gray-500", "bg": "bg-gray-500/10"}
        )
        prev_total = last_month_lookup.get(row.id, 0)

        # Calculate % Change
        if prev_total > 0:
            change = ((float(row.total) - prev_total) / prev_total) * 100
            change_txt = f"{'+' if change > 0 else ''}{change:.0f}%"
            change_color = "text-red-500" if change > 0 else "text-green-500"
            change_bg = "bg-red-500/10" if change > 0 else "bg-green-500/10"
        else:
            change_txt = "0%"
            change_color = "text-gray-500"
            change_bg = "bg-gray-500/10"

        # Calculate % of Total Month
        pct_share = (float(row.total) / total_month_spent * 100) if total_month_spent > 0 else 0
        footer_legend.append(
            f'<span class="flex items-center"><span class="w-2 h-2 rounded-full {cat_config["color"]} mr-1.5"></span> {row.name} {pct_share:.0f}%</span>'
        )

        html += f"""
        <div class="group flex items-center justify-between p-3 -mx-2 rounded-xl hover:bg-white/5 transition cursor-pointer"
             hx-get="/api/items/list?category_id={row.id}" hx-target="#modal-content" hx-swap="innerHTML"
             onclick='document.getElementById("category-items-modal").classList.remove("hidden")'>

            <div class="flex items-center space-x-4">
                <div class="w-12 h-12 rounded-xl {cat_config["bg"]} flex items-center justify-center text-2xl group-hover:scale-110 transition">
                    {cat_config["icon"]}
                </div>
                <div>
                    <h3 class="text-base font-bold text-white">{row.name}</h3>
                    <p class="text-xs text-gray-500 font-medium">{row.item_count} items · {row.store_count} stores</p>
                </div>
            </div>

            <div class="flex items-center space-x-6">
                <!-- Progress Bar -->
                <div class="hidden md:block w-32 h-1.5 bg-gray-800 rounded-full overflow-hidden">
                    <div class="h-full {cat_config["color"]}" style="width: {pct_share}%"></div>
                </div>

                <div class="text-right">
                    <span class="text-lg font-black text-white">${row.total:.0f}</span>
                </div>

                <div class="w-14 text-right">
                    <span class="inline-block px-2 py-1 rounded text-[10px] font-bold {change_bg} {change_color}">
                        {change_txt}
                    </span>
                </div>
            </div>
        </div>
        """

    html += f"""
        </div>

        <div class="mt-8 pt-4 border-t border-gray-800">
            <div class="flex flex-wrap gap-x-6 gap-y-2 text-[10px] font-bold text-gray-500 uppercase tracking-widest">
                {" ".join(footer_legend)}
            </div>
        </div>
    </div>
    """
    return html


@router.get("/tables/top-items", response_class=HTMLResponse)
def get_top_items_html(limit: int = 8, db: Session = Depends(get_db)):
    """Get HTML table for top items"""
    results = (
        db.query(Item.name, func.sum(ReceiptItem.price * ReceiptItem.quantity).label("total"))
        .join(ReceiptItem, Item.id == ReceiptItem.item_id)
        .outerjoin(Category, Item.category_id == Category.id)
        .filter(
            or_(
                Category.name.is_(None),
                Category.name.notin_(
                    ["Excluded", "Other", "Fees & Taxes", "CRV (tax)", "Non-Alcoholic Beer"]
                ),
            )
        )
        .group_by(Item.id, Item.name)
        .order_by(func.sum(ReceiptItem.price * ReceiptItem.quantity).desc())
        .limit(limit)
        .all()
    )

    html = """
    <div class="overflow-hidden rounded-lg border border-gray-200 dark:border-gray-700">
        <table class="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
            <thead class="bg-gray-50 dark:bg-gray-700/50">
                <tr>
                    <th scope="col" class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Item</th>
                    <th scope="col" class="px-4 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Spent</th>
                </tr>
            </thead>
            <tbody class="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
    """

    for name, total in results:
        html += f"""
            <tr>
                <td class="px-4 py-2 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-white truncate max-w-[150px]" title="{name}">{name}</td>
                <td class="px-4 py-2 whitespace-nowrap text-sm text-right text-gray-500 dark:text-gray-400">${total:.2f}</td>
            </tr>
        """

    html += """
            </tbody>
        </table>
    </div>
    """
    return html


@router.get("/tables/store-spend", response_class=HTMLResponse)
def get_store_spend_html(db: Session = Depends(get_db)):
    """Get HTML table for store spending with graph button"""
    results = (
        db.query(
            Store.id, Store.name, func.sum(ReceiptItem.price * ReceiptItem.quantity).label("total")
        )
        .join(Receipt, Store.id == Receipt.store_id)
        .join(ReceiptItem, Receipt.id == ReceiptItem.receipt_id)
        .join(Item, ReceiptItem.item_id == Item.id)
        .outerjoin(Category, Item.category_id == Category.id)
        .filter(
            or_(
                Category.name.is_(None),
                Category.name.notin_(
                    ["Excluded", "Other", "Fees & Taxes", "CRV (tax)", "Non-Alcoholic Beer"]
                ),
            )
        )
        .group_by(Store.id, Store.name)
        .order_by(func.sum(ReceiptItem.price * ReceiptItem.quantity).desc())
        .all()
    )

    html = """
    <div class="overflow-hidden rounded-lg border border-gray-200 dark:border-gray-700" x-data="{ showAll: false }">
        <table class="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
            <thead class="bg-gray-50 dark:bg-gray-700/50 hidden sm:table-header-group">
                <tr>
                    <th scope="col" class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Store</th>
                    <th scope="col" class="px-4 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Total</th>
                    <th scope="col" class="px-4 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Action</th>
                </tr>
            </thead>
            <tbody class="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700 flex flex-col sm:table-row-group">
    """

    for idx, (store_id, name, total) in enumerate(results):
        safe_name = name.replace("'", "\\'")
        hidden_class = 'x-show="showAll || ' + str(idx) + ' < 8"'
        html += f"""
            <tr {hidden_class}
                class="flex flex-wrap sm:table-row items-center justify-between p-2 sm:p-0"
                x-transition:enter="transition ease-out duration-200"
                x-transition:enter-start="opacity-0 transform -translate-y-1"
                x-transition:enter-end="opacity-100 transform translate-y-0">
                <td class="px-2 sm:px-4 py-1 sm:py-2 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-white truncate max-w-[200px] sm:max-w-[150px] w-full sm:w-auto" title="{name}">{name}</td>
                <td class="px-2 sm:px-4 py-1 sm:py-2 whitespace-nowrap text-sm text-left sm:text-right text-gray-500 dark:text-gray-400 w-1/2 sm:w-auto">${total:.2f}</td>
                <td class="px-2 sm:px-4 py-1 sm:py-2 whitespace-nowrap text-sm text-right w-1/2 sm:w-auto">
                    <button onclick="showStoreHistory({store_id}, '{safe_name}')"
                            class="text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 ml-auto flex">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z"></path></svg>
                    </button>
                </td>
            </tr>
        """

    html += f"""
            </tbody>
        </table>
        {
        f'''
        <div class="p-2 bg-gray-50 dark:bg-gray-900/50 border-t border-gray-200 dark:border-gray-700 text-center">
            <button @click="showAll = !showAll"
                    class="text-xs font-black text-blue-600 dark:text-blue-400 hover:underline uppercase tracking-widest">
                <span x-text="showAll ? 'Show Less' : 'Show All ({len(results)})'"></span>
            </button>
        </div>
        '''
        if len(results) > 8
        else ""
    }
    </div>
    """
    return html


def _calculate_unit_price(price: float, qty: float, weight: float, unit: str, category_type: str):
    """
    Helper to calculate price per primary unit.
    Returns (price_per_primary, primary_unit_label, secondary_value)
    """
    if not price or not qty or not weight or not unit:
        return None, None, None

    u = unit.lower().strip()
    price_per_primary = None
    primary_label = None
    secondary_value = None

    # Determine primary unit based on category
    if category_type in ["meat", "produce"]:
        # Primary is $/lb
        primary_label = "$/lb"
        wt_lb = 0
        if u == "lb":
            wt_lb = weight
        elif u == "oz":
            wt_lb = weight / 16.0
        elif u == "kg":
            wt_lb = weight * 2.20462
        elif u == "g":
            wt_lb = weight * 0.00220462

        if wt_lb > 0:
            price_per_primary = price / wt_lb
    else:
        # Primary is $/oz (Beverages, Pantry, Dairy)
        primary_label = "$/oz"
        wt_oz = 0
        if u in ["oz", "fl oz"]:
            wt_oz = weight
        elif u == "lb":
            wt_oz = weight * 16.0
        elif u == "kg":
            wt_oz = weight * 35.274
        elif u == "g":
            wt_oz = weight * 0.035274
        elif u == "l":
            wt_oz = weight * 33.814
        elif u == "ml":
            wt_oz = weight * 0.033814
        elif u == "cl":
            wt_oz = weight * 0.33814
        elif u == "pt":
            wt_oz = weight * 16
        elif u == "qt":
            wt_oz = weight * 32
        elif u == "gal":
            wt_oz = weight * 128

        if wt_oz > 0:
            price_per_primary = price / wt_oz
            if category_type == "beverages":
                secondary_value = price_per_primary * 12  # $/12oz

    return price_per_primary, primary_label, secondary_value


def _get_category_price_data(
    category_filter: str, cat_type: str, db: Session, limit: int = None, offset: int = 0
):
    """
    Unified helper for best-value widgets.
    Filters items by category and calculates unit prices using the specified cat_type logic.
    """
    results = (
        db.query(
            Item.name,
            ReceiptItem.price,
            ReceiptItem.quantity,
            ReceiptItem.weight,
            ReceiptItem.unit_type,
            Receipt.purchase_date,
            Store.name,
            Receipt.id,
        )
        .join(Item, ReceiptItem.item_id == Item.id)
        .outerjoin(Category, Item.category_id == Category.id)
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .join(Store, Receipt.store_id == Store.id)
        .filter(Category.name.ilike(f"%{category_filter}%"))
        .all()
    )

    item_best_prices = {}
    for name, price, qty, weight, unit, date, store_name, receipt_id in results:
        price_per_unit, _, secondary = _calculate_unit_price(price, qty, weight, unit, cat_type)

        if name not in item_best_prices:
            item_best_prices[name] = {
                "name": name,
                "price_per_primary": price_per_unit,
                "secondary_value": secondary,
                "unit_price": (price / qty) if qty and price else 0,
                "store": store_name,
                "date": date,
                "receipt_id": receipt_id,
            }
        elif price_per_unit is not None:
            current_best = item_best_prices[name]["price_per_primary"]
            if current_best is None or price_per_unit < current_best:
                item_best_prices[name].update(
                    {
                        "price_per_primary": price_per_unit,
                        "secondary_value": secondary,
                        "unit_price": (price / qty),
                        "store": store_name,
                        "date": date,
                        "receipt_id": receipt_id,
                    }
                )

    # Sort: Items with price first (ascending), then None values
    sorted_items = sorted(
        item_best_prices.values(),
        key=lambda x: (
            x["price_per_primary"] is None,
            x["price_per_primary"] or 999999,
        ),
    )
    if limit:
        return sorted_items[offset : offset + limit]
    return sorted_items[offset:]


@router.get("/tables/best-value/{category}", response_class=HTMLResponse)
def get_category_comparison_html(category: str, limit: int = 10, db: Session = Depends(get_db)):
    """Unified endpoint for category best-value tables (Fixed Audit #5.47)"""
    # Map friendly names to technical category types
    category_map = {
        "beverages": "beverage",
        "meat": "meat",
        "pantry": "pantry",
        "dairy": "dairy",
        "produce": "produce",
    }

    cat_type = category_map.get(category, category)

    # Map category to display config
    config = {
        "beverages": ("$/oz", "text-green-600 dark:text-green-400"),
        "meat": ("$/lb", "text-red-600 dark:text-red-400"),
        "pantry": ("$/unit", "text-yellow-600 dark:text-yellow-400"),
        "dairy": ("$/unit", "text-blue-600 dark:text-blue-400"),
        "produce": ("$/lb", "text-green-600 dark:text-green-400"),
    }

    unit_label, color_class = config.get(category, ("$/unit", "text-blue-600 dark:text-blue-400"))

    items = _get_category_price_data(cat_type, category, db, limit=limit)
    return _render_summary_table(items, unit_label, color_class)


def _render_summary_table(
    items: list, unit_label: str, color_class: str = "text-blue-600 dark:text-blue-400"
):
    """Helper: Render a summary table for best-value widgets with responsive design"""
    html = f"""
    <div class="rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden divide-y divide-gray-200 dark:divide-gray-700">
        <!-- Header (Desktop Only) -->
        <div class="hidden lg:grid lg:grid-cols-12 gap-4 bg-gray-50 dark:bg-gray-700/50 px-4 py-3 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
            <div class="col-span-6">Item</div>
            <div class="col-span-3 text-right">{unit_label}</div>
            <div class="col-span-3 text-right">Store</div>
        </div>
        <div class="bg-white dark:bg-gray-800 divide-y divide-gray-100 dark:divide-gray-700/50">
    """

    for idx, item in enumerate(items):
        price_display = (
            f"${item['price_per_primary']:.2f}"
            if item["price_per_primary"] is not None
            else '<span class="text-gray-400">N/A</span>'
        )

        # Determine visibility based on limit (5 mobile, 10 desktop)
        # Note: items list is already limited to 10 in the route
        visibility_class = "flex" if idx < 5 else "hidden lg:flex"

        html += f"""
            <div class="{visibility_class} flex-col lg:grid lg:grid-cols-12 gap-2 lg:gap-4 px-4 py-4 lg:py-3 transition-colors hover:bg-gray-50 dark:hover:bg-gray-700/30">
                <!-- Item Name -->
                <div class="col-span-6 text-sm font-medium text-gray-900 dark:text-white truncate max-w-[280px] min-[400px]:max-w-none" title="{item["name"]}">
                    {item["name"]}
                </div>

                <!-- Price and Store (Wrapped on mobile) -->
                <div class="flex justify-between items-center lg:contents mt-1 lg:mt-0">
                    <div class="lg:col-span-3 text-sm lg:text-right {color_class} font-bold font-mono">
                        <span class="lg:hidden text-[10px] uppercase text-gray-400 mr-1">{unit_label}:</span>
                        {price_display}
                    </div>
                    <div class="lg:col-span-3 text-sm lg:text-right text-gray-500 dark:text-gray-400 truncate lg:max-w-none max-w-[150px]" title="{item["store"]}">
                        <span class="lg:hidden text-[10px] uppercase text-gray-400 mr-1">Store:</span>
                        {item["store"]}
                    </div>
                </div>
            </div>
        """

    html += "</div></div>"
    return html


# --- Full Page Endpoints ---


@router.get("/tables/best-value/{category_type}/rows", response_class=HTMLResponse)
def get_best_value_rows(
    category_type: str, limit: int = 25, offset: int = 0, db: Session = Depends(get_db)
):
    """HTMX endpoint for table rows"""

    items = []
    items = _get_category_price_data(
        category_type, category_type if category_type != "pantry" else "pantry", db, limit, offset
    )

    html = ""
    for i, item in enumerate(items):
        is_last = i == len(items) - 1
        has_more = len(items) == limit

        trigger_attr = ""
        if is_last and has_more:
            trigger_attr = f'hx-get="/api/analytics/tables/best-value/{category_type}/rows?limit={limit}&offset={offset + limit}" hx-trigger="revealed" hx-swap="afterend"'

        color_class = "text-gray-900 dark:text-white"
        if category_type == "beverages":
            color_class = "text-green-600 dark:text-green-400 font-bold"
        elif category_type == "meat":
            color_class = "text-red-600 dark:text-red-400 font-bold"
        elif category_type == "pantry":
            color_class = "text-yellow-600 dark:text-yellow-400 font-bold"
        elif category_type == "dairy":
            color_class = "text-blue-600 dark:text-blue-400 font-bold"
        elif category_type == "produce":
            color_class = "text-green-600 dark:text-green-400 font-bold"

        # Handle missing pricing data
        price_display = (
            f"${item['price_per_primary']:.2f}"
            if item["price_per_primary"] is not None
            else '<span class="text-gray-400">N/A</span>'
        )
        unit_price_display = (
            f"${item['unit_price']:.2f}"
            if item["unit_price"]
            else '<span class="text-gray-400">N/A</span>'
        )

        date_str = item["date"].strftime("%Y-%m-%d") if item["date"] else "N/A"

        # Row container: flex-col on mobile, 12-col grid on desktop
        html += f"""
        <div {trigger_attr} class="flex flex-col lg:grid lg:grid-cols-12 gap-2 lg:gap-4 px-6 py-4 lg:py-3 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors">
            <!-- Item Name -->
            <div class="lg:col-span-4 text-sm font-medium text-gray-900 dark:text-white truncate" title='{item["name"]}'>
                {item["name"]}
            </div>

            <!-- Secondary Info (Wrapped on mobile) -->
            <div class="flex flex-wrap items-center gap-x-4 gap-y-2 lg:contents">
                <!-- Unit Price -->
                <div class="lg:col-span-2 text-sm lg:text-right {color_class} font-mono">
                    <span class="lg:hidden text-[10px] uppercase text-gray-400 mr-1">Unit:</span>
                    {price_display}
                </div>

                <!-- Base Price -->
                <div class="lg:col-span-2 text-sm lg:text-right text-gray-900 dark:text-gray-100 font-medium">
                    <span class="lg:hidden text-[10px] uppercase text-gray-400 mr-1">Price:</span>
                    {unit_price_display}
                </div>
        """

        if category_type == "beverages":
            sec_display = (
                f"${item['secondary_value']:.2f}"
                if item["secondary_value"] is not None
                else '<span class="text-gray-400">N/A</span>'
            )
            html += f"""
                <div class="lg:col-span-1 text-sm lg:text-right text-gray-500 dark:text-gray-400">
                    <span class="lg:hidden text-[10px] uppercase text-gray-400 mr-1">/12oz:</span>
                    {sec_display}
                </div>
                <div class="lg:col-span-2 text-sm lg:text-right text-gray-500 dark:text-gray-400 truncate max-w-[150px] lg:max-w-none">
                    <span class="lg:hidden text-[10px] uppercase text-gray-400 mr-1">Store:</span>
                    {item["store"]}
                </div>
            """
        else:
            html += f"""
                <div class="lg:col-span-2 text-sm lg:text-right text-gray-500 dark:text-gray-400 truncate max-w-[150px] lg:max-w-none">
                    <span class="lg:hidden text-[10px] uppercase text-gray-400 mr-1">Store:</span>
                    {item["store"]}
                </div>
            """

        html += f"""
                <div class="lg:col-span-1 text-sm lg:text-right">
                    <a href="/receipts/{item["receipt_id"]}/review" class="text-blue-600 dark:text-blue-400 hover:underline inline-flex items-center gap-1" title="View Receipt">
                        <span class="lg:hidden text-[10px] uppercase text-gray-400 mr-1">Date:</span>
                        {date_str}
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path></svg>
                    </a>
                </div>
            </div>
        </div>
        """

    return html


# --- Shopping Basket Feature ---


@router.get("/tables/basket-by-store", response_class=HTMLResponse)
def get_basket_by_store_html(limit: int = 10, db: Session = Depends(get_db)):
    """
    Compare the cost of the Shopping Basket across different stores.
    """
    top_item_ids = _get_top_items(db, limit)

    if not top_item_ids:
        return "<div>No items found to build a basket.</div>"

    # 1. Calculate global average/latest price for each item as a fallback (Fixed N+1)
    global_fallback = {}
    latest_prices = (
        db.query(ReceiptItem.item_id, ReceiptItem.price, ReceiptItem.quantity)
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .filter(ReceiptItem.item_id.in_(top_item_ids))
        .order_by(ReceiptItem.item_id, Receipt.purchase_date.desc())
        .all()
    )
    # Since we ordered by date desc, the first one seen per item_id is the latest
    for item_id, price, qty in latest_prices:
        if item_id not in global_fallback and qty > 0:
            global_fallback[item_id] = float(price / qty)

    # 2. Get all stores and their latest prices for these items (Fixed N+1)
    stores = db.query(Store).all()

    # Store-Item price map: {store_id: {item_id: price}}
    store_item_prices = {}
    all_store_history = (
        db.query(Receipt.store_id, ReceiptItem.item_id, ReceiptItem.price, ReceiptItem.quantity)
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .filter(ReceiptItem.item_id.in_(top_item_ids))
        .order_by(Receipt.store_id, ReceiptItem.item_id, Receipt.purchase_date.desc())
        .all()
    )
    for s_id, i_id, p, q in all_store_history:
        if s_id not in store_item_prices:
            store_item_prices[s_id] = {}
        if i_id not in store_item_prices[s_id] and q > 0:
            store_item_prices[s_id][i_id] = float(p / q)

    store_totals = []  # [(store_name, total_cost, missing_count)]

    for store in stores:
        store_cost = 0.0
        missing_count = 0
        prices_at_store = store_item_prices.get(store.id, {})

        for item_id in top_item_ids:
            if item_id in prices_at_store:
                store_cost += prices_at_store[item_id]
            else:
                # Use global fallback
                store_cost += global_fallback.get(item_id, 0.0)
                missing_count += 1

        # Only include stores where they actually buy a decent amount of the basket
        # If they've never bought 80% of the basket there, it's not a real grocery store comparison
        if missing_count < len(top_item_ids) * 0.8:
            store_totals.append({"name": store.name, "cost": store_cost, "missing": missing_count})

    # Sort from cheapest to most expensive
    store_totals.sort(key=lambda x: x["cost"])

    # Build HTML
    html = """
    <div class="overflow-hidden rounded-lg border border-gray-200 dark:border-gray-700">
        <table class="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
            <thead class="bg-gray-50 dark:bg-gray-700/50">
                <tr>
                    <th scope="col" class="px-4 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Store</th>
                    <th scope="col" class="px-4 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Basket Cost</th>
                    <th scope="col" class="px-4 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">Est. Items</th>
                </tr>
            </thead>
            <tbody class="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
    """

    for st in store_totals:
        missing_badge = ""
        if st["missing"] > 0:
            missing_badge = f'<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-yellow-100 dark:bg-yellow-900/30 text-yellow-800 dark:text-yellow-400" title="{st["missing"]} items substituted with global average">{st["missing"]} est.</span>'
        else:
            missing_badge = '<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-400">Exact</span>'

        html += f"""
            <tr>
                <td class="px-4 py-3 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-white truncate max-w-[120px] sm:max-w-none" title="{st["name"]}">{st["name"]}</td>
                <td class="px-4 py-3 whitespace-nowrap text-sm text-right font-mono font-bold text-gray-900 dark:text-white">${st["cost"]:.2f}</td>
                <td class="px-4 py-3 whitespace-nowrap text-right">{missing_badge}</td>
            </tr>
        """

    html += "</tbody></table></div>"
    return html


@router.get("/widgets/category-store-stack", response_class=HTMLResponse)
def get_category_store_stack_widget(db: Session = Depends(get_db)):
    """
    Get a horizontally stacked spending-by-category-and-store widget.
    Categories sorted by total spent. Stores sorted by average unit price (best value).
    """
    # Fetch all relevant items
    results = (
        db.query(
            Category.id,
            Category.name,
            Store.id,
            Store.name,
            ReceiptItem.price,
            ReceiptItem.quantity,
            ReceiptItem.weight,
            ReceiptItem.unit_type,
            Receipt.id,
        )
        .join(Item, Category.id == Item.category_id)
        .join(ReceiptItem, Item.id == ReceiptItem.item_id)
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .join(Store, Receipt.store_id == Store.id)
        .all()
    )

    if not results:
        return (
            "<div class='p-4 text-gray-500'>No data available yet. Start scanning receipts!</div>"
        )

    # Process results
    # categories: category_id -> {name, total, stores: {store_id: {name, spent, unit_prices: []}}}
    categories = {}
    exclude_list = _get_analytics_exclusions(db)

    for cat_id, cat_name, store_id, store_name, price, qty, weight, unit, _receipt_id in results:
        if any(ex in cat_name.lower() for ex in exclude_list):
            continue

        if cat_id not in categories:
            categories[cat_id] = {"name": cat_name, "total": 0, "stores": {}, "id": cat_id}

        if store_id not in categories[cat_id]["stores"]:
            categories[cat_id]["stores"][store_id] = {
                "name": store_name,
                "spent": 0,
                "unit_prices": [],
            }

        item_total = (price * qty) if price and qty else 0
        categories[cat_id]["total"] += item_total
        categories[cat_id]["stores"][store_id]["spent"] += item_total

        # Calculate unit price for sorting (value metric)
        # Normalizing category type for unit price logic
        cat_type = "other"
        cl = cat_name.lower()
        if "meat" in cl:
            cat_type = "meat"
        elif "produce" in cl:
            cat_type = "produce"
        elif "dairy" in cl:
            cat_type = "dairy"
        elif "bev" in cl:
            cat_type = "beverages"
        elif "pantry" in cl:
            cat_type = "pantry"

        u_p, _, _ = _calculate_unit_price(price, qty, weight, unit, cat_type)
        if u_p:
            categories[cat_id]["stores"][store_id]["unit_prices"].append(u_p)

    # Sort categories by total spend and limit to top 10
    sorted_cats = sorted(categories.values(), key=lambda x: x["total"], reverse=True)[:10]

    html = '<div class="space-y-6 pt-2 pb-2">'
    for cat in sorted_cats:
        # Calculate average unit prices for sorting stores
        store_list = []
        for s_id, s_data in cat["stores"].items():
            avg_u_p = (
                sum(s_data["unit_prices"]) / len(s_data["unit_prices"])
                if s_data["unit_prices"]
                else 999999
            )
            store_list.append(
                {
                    "id": s_id,
                    "name": s_data["name"],
                    "spent": s_data["spent"],
                    "avg_unit_price": avg_u_p,
                }
            )

        # Sort stores by avg_unit_price (best value first)
        store_list.sort(key=lambda x: x["avg_unit_price"])

        cat_total = cat["total"]
        if cat_total < 0.01:
            continue

        html += '<div class="flex flex-col space-y-2">'
        html += '<div class="flex justify-between items-end px-1">'
        html += f'<span class="text-sm font-bold text-gray-700 dark:text-gray-200 uppercase tracking-wider">{cat["name"]}</span>'
        html += f'<span class="text-xs font-mono font-bold text-gray-500 dark:text-gray-400">${cat_total:,.2f}</span>'
        html += "</div>"

        # Stacked bar container
        html += '<div class="h-10 w-full flex rounded-xl overflow-hidden border border-gray-100 dark:border-gray-700/50 shadow-inner bg-gray-50 dark:bg-gray-900/40">'

        # Color palette for segments (Modern, premium colors)
        colors = [
            "bg-indigo-500",
            "bg-emerald-500",
            "bg-amber-500",
            "bg-rose-500",
            "bg-sky-500",
            "bg-violet-500",
            "bg-teal-500",
            "bg-orange-500",
            "bg-pink-500",
            "bg-lime-500",
        ]

        for idx, store in enumerate(store_list):
            pct = (store["spent"] / cat_total) * 100
            if pct < 0.5:
                continue  # Skip negligible segments

            color = colors[idx % len(colors)]
            # Fix: Use json.dumps() for secure JS escaping
            store_json = json.dumps(store["name"])
            cat_json = json.dumps(cat["name"])

            html += f"""
            <div class="{color} h-full transition-all hover:scale-[1.02] hover:z-10 hover:shadow-lg cursor-pointer group relative flex items-center justify-center min-w-[2px] overflow-hidden"
                 style="width: {pct}%"
                 onclick='showCategoryStoreDrilldown({cat["id"]}, {store["id"]}, {cat_json}, {store_json})'
                 title="{store["name"]}: ${store["spent"]:,.2f}">

                <!-- Overlay Store Name -->
                <span class="absolute inset-0 flex items-center justify-center pointer-events-none px-1">
                    <span class="text-[9px] font-black text-white/90 truncate drop-shadow-sm transition-opacity duration-300 {"opacity-0" if pct < 10 else "opacity-100"}" title="{store["name"]}">
                        {store["name"]}
                    </span>
                </span>

                <!-- Label shown on hover -->
                <span class="opacity-0 group-hover:opacity-100 transition-opacity text-[10px] font-black text-white whitespace-nowrap bg-black/60 px-1.5 py-0.5 rounded backdrop-blur-sm z-20 pointer-events-none absolute bottom-1">
                    ${store["spent"]:,.0f}
                </span>
            </div>
            """
        html += "</div></div>"

    html += "</div>"
    return html


@router.get("/drilldown/category-store/{category_id}/{store_id}", response_class=HTMLResponse)
def get_category_store_drilldown(category_id: int, store_id: int, db: Session = Depends(get_db)):
    """
    Get a list of receipts for a specific category and store.
    """
    from sqlalchemy import func

    results = (
        db.query(
            Receipt.id,
            Receipt.purchase_date,
            func.sum(ReceiptItem.price * ReceiptItem.quantity).label("category_spent"),
            Receipt.total_amount,
        )
        .join(ReceiptItem, Receipt.id == ReceiptItem.receipt_id)
        .join(Item, ReceiptItem.item_id == Item.id)
        .outerjoin(Category, Item.category_id == Category.id)
        .filter(Item.category_id == category_id)
        .filter(Receipt.store_id == store_id)
        .filter(
            Category.name.notin_(
                ["Excluded", "Other", "Fees & Taxes", "CRV (tax)", "Non-Alcoholic Beer"]
            )
        )
        .group_by(Receipt.id)
        .order_by(Receipt.purchase_date.desc())
        .all()
    )

    if not results:
        return """
        <div class="flex flex-col items-center justify-center p-12 text-center">
            <div class="w-16 h-16 bg-gray-100 dark:bg-gray-800 rounded-full flex items-center justify-center mb-4">
                <svg class="w-8 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                </svg>
            </div>
            <h3 class="text-lg font-bold text-gray-900 dark:text-white">No data found</h3>
            <p class="text-gray-500 dark:text-gray-400 max-w-xs mx-auto">We couldn't find any receipts for this specific category and store selection.</p>
        </div>
        """

    html = """
    <div class="overflow-x-auto">
        <table class="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
            <thead class="bg-gray-50 dark:bg-gray-700/50">
                <tr>
                    <th class="px-6 py-3 text-left text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Date</th>
                    <th class="px-6 py-3 text-right text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Category Contribution</th>
                    <th class="px-6 py-3 text-right text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Receipt Total</th>
                    <th class="px-6 py-3 text-right text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Action</th>
                </tr>
            </thead>
            <tbody class="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
    """
    for r_id, date, cat_spent, total in results:
        html += f"""
        <tr class="hover:bg-blue-50/30 dark:hover:bg-blue-900/10 transition group">
            <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-white">{date.strftime("%b %d, %Y") if date else "N/A"}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-right font-black text-indigo-600 dark:text-indigo-400">${cat_spent:,.2f}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-right text-gray-500 dark:text-gray-400 font-mono">${total:,.2f}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-right">
                <a href="/receipts/{r_id}/review" class="inline-flex items-center space-x-1 text-blue-600 dark:text-blue-400 font-bold hover:underline">
                    <span>View</span>
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path></svg>
                </a>
            </td>
        </tr>
        """
    html += "</tbody></table></div>"
    return html


