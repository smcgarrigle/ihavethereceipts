#!/usr/bin/env python3
"""
Enrich Unmatched Items via USDA FDC Lookup.

Queries items in the database that currently lack an FDC ID / OFF Code,
filters out non-food items (Fees, Taxes, Household items), and attempts
USDA FDC (and fallback OpenFoodFacts) lookups to enrich nutrient and category data.
"""

import sys
import time
from pathlib import Path

# Setup paths
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir / "backend"))

from dotenv import load_dotenv
load_dotenv(root_dir / "backend" / ".env")

from app.database import SessionLocal
from app.models import Category, Item
from app.services.fdc_service import fdc_service
from app.services.external_product import OpenFoodFactsService

def enrich_unmatched_items():
    db = SessionLocal()
    try:
        # Fetch unmatched items
        unmatched_items = db.query(Item).filter(
            (Item.fdc_id.is_(None) | (Item.fdc_id == 0)),
            (Item.off_code.is_(None) | (Item.off_code == ""))
        ).join(Category, Item.category_id == Category.id, isouter=True).order_by(Category.name, Item.name).all()

        print(f"Loaded {len(unmatched_items)} unmatched items from database.")

        non_food_keywords = [
            "deposit", "crv", "tax", "fee", "refund", "subtotal", "bag credit", "driver tip",
            "payment methods", "gift card", "gasoline", "tshirt", "jersey", "jacket", "shin guard",
            "hanger", "incense", "butane", "wax paper", "aluminum foil", "bath tissue", "bleach",
            "hand soap", "dish bulk", "mister", "shower towel", "bio tub", "roller box", "cleaner",
            "acuvue", "nitrile exam gloves"
        ]

        attempted = 0
        fdc_matched = 0
        off_matched = 0
        skipped = 0

        for idx, item in enumerate(unmatched_items, 1):
            cat_name = item.category.name if item.category else ""
            norm_name = (item.name or "").lower()

            # Skip non-food fees and household items
            if cat_name in ["Fees & Taxes", "Household"] or any(kw in norm_name for kw in non_food_keywords):
                skipped += 1
                continue

            attempted += 1
            print(f"[{idx}/{len(unmatched_items)}] Attempting FDC lookup for: '{item.name}' (Category: {cat_name})")

            # 1. Attempt FDC lookup and enrichment
            success = fdc_service.enrich_db_item(db, item.id)
            if success:
                fdc_matched += 1
                db.refresh(item)
                print(f"  ✓ FDC Matched! FDC ID: {item.fdc_id}")
            else:
                # 2. Attempt OFF fallback if FDC produced no match
                off_success = OpenFoodFactsService.enrich_db_item(db, item.id)
                if off_success:
                    off_matched += 1
                    db.refresh(item)
                    print(f"  ✓ OFF Fallback Matched! Code: {item.off_code}")
                else:
                    print(f"  ✗ No match found.")

            time.sleep(0.2)

        print("\n=== Lookup Summary ===")
        print(f"Total Unmatched Checked: {len(unmatched_items)}")
        print(f"Non-Food/Fee Skipped  : {skipped}")
        print(f"Food Items Attempted  : {attempted}")
        print(f"FDC Matched           : {fdc_matched}")
        print(f"OFF Matched           : {off_matched}")
        print(f"Total Enriched        : {fdc_matched + off_matched}")

    finally:
        db.close()

if __name__ == "__main__":
    enrich_unmatched_items()
