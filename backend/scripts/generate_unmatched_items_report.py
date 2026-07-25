#!/usr/bin/env python3
import sys
from pathlib import Path

# Setup paths
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir / "backend"))

from dotenv import load_dotenv
load_dotenv(root_dir / "backend" / ".env")

from app.database import SessionLocal
from app.models import Category, Item, ReceiptItem, Receipt, Store
from sqlalchemy import func

def generate_unmatched_report():
    db = SessionLocal()
    try:
        # Query items with no FDC ID and no OFF Code
        items = db.query(Item).filter(
            (Item.fdc_id.is_(None) | (Item.fdc_id == 0)),
            (Item.off_code.is_(None) | (Item.off_code == ""))
        ).join(Category, Item.category_id == Category.id, isouter=True)\
         .order_by(Category.name, Item.name).all()

        print(f"Found {len(items)} items without USDA FDC or OpenFoodFacts match.")

        # Summary statistics by category
        cat_counts = {}
        report_rows = []

        for item in items:
            cat_name = item.category.name if item.category else "Unassigned"
            cat_counts[cat_name] = cat_counts.get(cat_name, 0) + 1

            # Fetch receipt stats for this item
            receipt_items = db.query(ReceiptItem).filter(ReceiptItem.item_id == item.id).all()
            purchase_count = len(receipt_items)

            latest_price = "$0.00"
            primary_store = "Unknown Store"

            if receipt_items:
                # Find most recent purchase
                latest_ri = max(receipt_items, key=lambda ri: ri.receipt_id)
                if latest_ri.unit_price and latest_ri.unit_price > 0:
                    latest_price = f"${latest_ri.unit_price:.2f}"
                elif latest_ri.price and latest_ri.price > 0:
                    latest_price = f"${latest_ri.price:.2f}"

                # Store name
                receipt = db.query(Receipt).filter(Receipt.id == latest_ri.receipt_id).first()
                if receipt and receipt.store:
                    primary_store = receipt.store.name

            # Determine enrichment note / recommendation
            norm = (item.name or "").lower()
            if cat_name == "Fees & Taxes" or any(kw in norm for kw in ["deposit", "crv", "tax", "fee", "refund", "total", "subtotal", "bag credit", "driver tip", "payment methods"]):
                note = "Excluded (Non-food fee/tax)"
            elif cat_name == "Household" or any(kw in norm for kw in ["soap", "shampoo", "candle", "towel", "foil", "battery", "detergent", "lotion", "incense", "hanger", "butane", "cleaner", "glove", "jersey", "jacket", "shin guard", "balloon", "banner"]):
                note = "Non-food household item"
            elif cat_name in ["Produce", "Meat"]:
                note = "Raw / Fresh item (Needs FDC search)"
            else:
                note = "Packaged food (Needs GTIN / FDC lookup)"

            report_rows.append({
                "name": item.name,
                "category": cat_name,
                "store": primary_store,
                "purchases": purchase_count,
                "price": latest_price,
                "note": note
            })

        # Sort report rows by Category then Item Name
        report_rows.sort(key=lambda r: (r["category"], r["name"]))

        # Build Markdown content
        md_lines = ["# Items Without USDA FDC or OpenFoodFacts Match\n"]
        md_lines.append(f"**Total Unmatched Items**: {len(items)}\n")

        # Category Summary Table
        md_lines.append("## Breakdown by Category\n")
        md_lines.append("| Category | Unmatched Item Count |")
        md_lines.append("| :--- | :--- |")
        for cat_name, count in sorted(cat_counts.items(), key=lambda x: (-x[1], x[0])):
            md_lines.append(f"| {cat_name} | {count} |")
        md_lines.append("")

        # Detailed Itemized Table
        md_lines.append("## Detailed Item List\n")
        md_lines.append("| Item Name | Category | Primary Store | Purchases | Latest Price | Recommended Action |")
        md_lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")

        for row in report_rows:
            # Escape pipe characters in item names if any
            clean_name = row["name"].replace("|", "\\|")
            md_lines.append(
                f"| {clean_name} | {row['category']} | {row['store']} | {row['purchases']} | {row['price']} | {row['note']} |"
            )

        output_path = root_dir / "unmatched_items_report.md"
        output_path.write_text("\n".join(md_lines) + "\n")
        print(f"Successfully generated {output_path} with {len(report_rows)} rows.")

    finally:
        db.close()

if __name__ == "__main__":
    generate_unmatched_report()
