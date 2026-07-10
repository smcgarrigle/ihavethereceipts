#!/usr/bin/env python3
import sys
from pathlib import Path

# Setup paths
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir / "backend"))

from dotenv import load_dotenv

load_dotenv(root_dir / "backend" / ".env")

from app.database import SessionLocal
from app.models import Category, Item, Receipt, ReceiptItem, Store


def generate_reports():
    db = SessionLocal()
    try:
        # 1. Find the "Other" category
        other_cat = db.query(Category).filter(Category.name == "Other").first()
        if not other_cat:
            print("Error: 'Other' category not found in database.")
            return

        # 2. Get all items in the 'Other' category
        items = db.query(Item).filter(Item.category_id == other_cat.id).all()
        print(f"Found {len(items)} items in 'Other' category.")

        if not items:
            print("Nothing to report.")
            return

        # 3. Group by Store
        # Data structure: stores[store_name][item_name] = { 'price': price, 'receipts': [id1, id2] }
        stores_data = {}

        for item in items:
            # Find all receipt items for this item
            receipt_items = db.query(ReceiptItem).filter(ReceiptItem.item_id == item.id).all()

            for ri in receipt_items:
                receipt = db.query(Receipt).filter(Receipt.id == ri.receipt_id).first()
                if not receipt:
                    continue

                store = db.query(Store).filter(Store.id == receipt.store_id).first()
                store_name = store.name if store else "Unknown Store"

                if store_name not in stores_data:
                    stores_data[store_name] = {}

                if item.name not in stores_data[store_name]:
                    stores_data[store_name][item.name] = {
                        "latest_price": ri.price,
                        "receipts": set(),
                    }

                stores_data[store_name][item.name]["receipts"].add(receipt.id)
                # Keep the price from the most recent receipt (optional refinement)
                # For now just use the one we found

        # Sort store names
        sorted_stores = sorted(stores_data.keys())

        # 4. Generate Markdown
        md_lines = ["# Items in Category Other\n"]
        for store_name in sorted_stores:
            md_lines.append(f"## {store_name}")
            store_items = stores_data[store_name]
            # Sort item names
            for item_name in sorted(store_items.keys()):
                data = store_items[item_name]
                receipt_links = ", ".join(
                    [f"[{rid}](/receipts/{rid}/review)" for rid in sorted(data["receipts"])]
                )
                md_lines.append(
                    f"- {item_name}   {data['latest_price']:.2f}   (Receipt Links: {receipt_links})"
                )
            md_lines.append("")  # Blank line between stores

        md_content = "\n".join(md_lines)
        with open(root_dir / "other_categories.md", "w") as f:
            f.write(md_content)
        print(f"Updated {root_dir}/other_categories.md")

        # 5. Generate HTML
        html_template = """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Review: Other Categories</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
        }
    </script>
</head>
<body class="bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 font-sans p-6 transition-colors duration-200">
    <div class="max-w-4xl mx-auto">
        <div class="flex items-center justify-between mb-8">
            <h1 class="text-3xl font-bold text-blue-600 dark:text-blue-400">Needs Review: 'Other' Category</h1>
            <span class="px-3 py-1 bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 rounded-full text-sm font-medium">
                {total_items} Items Total
            </span>
        </div>

        {stores_html}
    </div>
</body>
</html>"""

        store_section_template = """
        <div class="mb-8 bg-white dark:bg-gray-800 rounded-xl shadow-lg dark:shadow-gray-950/50 overflow-hidden border border-gray-100 dark:border-gray-700">
            <div class="px-6 py-4 bg-gray-50 dark:bg-gray-750 border-b border-gray-200 dark:border-gray-600">
                <h2 class="text-xl font-bold flex items-center gap-2">
                    <svg class="w-5 h-5 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 11V7a4 4 0 00-8 0v4M5 9h14l1 12H4L5 9z"></path></svg>
                    {store_name}
                </h2>
            </div>
            <ul class="divide-y divide-gray-100 dark:divide-gray-700">
                {items_html}
            </ul>
        </div>"""

        item_row_template = """
                <li class="px-6 py-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4 hover:bg-gray-50 dark:hover:bg-gray-750/50 transition duration-150">
                    <div class="flex-1">
                        <p class="font-semibold text-gray-800 dark:text-gray-200">{item_name}</p>
                    </div>
                    <div class="flex items-center gap-6">
                        <span class="font-mono text-lg font-bold text-green-600 dark:text-green-400">${price:.2f}</span>
                        <div class="flex flex-wrap gap-2">
                            {receipt_links_html}
                        </div>
                    </div>
                </li>"""

        receipt_link_template = """<a href="/receipts/{rid}/review" target="_blank" class="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold text-blue-700 bg-blue-50 border border-blue-100 rounded-md hover:bg-blue-100 dark:bg-blue-900/20 dark:text-blue-300 dark:border-blue-800 dark:hover:bg-blue-900/40 transition">
                                Receipt #{rid}
                                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path></svg>
                            </a>"""

        stores_html = ""
        total_unique_items = 0
        for store_name in sorted_stores:
            items_html = ""
            store_items = stores_data[store_name]
            for item_name in sorted(store_items.keys()):
                total_unique_items += 1
                data = store_items[item_name]
                receipt_links_html = "".join(
                    [receipt_link_template.format(rid=rid) for rid in sorted(data["receipts"])]
                )
                items_html += item_row_template.format(
                    item_name=item_name,
                    price=data["latest_price"],
                    receipt_links_html=receipt_links_html,
                )
            stores_html += store_section_template.format(
                store_name=store_name, items_html=items_html
            )

        final_html = html_template.replace("{total_items}", str(len(items))).replace(
            "{stores_html}", stores_html
        )

        with open(root_dir / "backend" / "static" / "other_categories.html", "w") as f:
            f.write(final_html)
        print(f"Updated {root_dir}/backend/static/other_categories.html")

    finally:
        db.close()


if __name__ == "__main__":
    generate_reports()
