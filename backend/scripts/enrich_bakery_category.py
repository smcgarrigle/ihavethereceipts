#!/usr/bin/env python3
import sys
import time
import re
from pathlib import Path

# Setup paths
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir / "backend"))

from dotenv import load_dotenv
load_dotenv(root_dir / "backend" / ".env")

from app.database import SessionLocal
from app.models import Category, Item
from app.services.fdc_service import FDCService
from app.services.external_product import OpenFoodFactsService

def clean_item_name(name: str) -> str:
    """Clean OCR noise and long metadata strings for search queries."""
    q = name
    q = q.split("KNG-")[0].split("BRM-")[0].split("Sold by:")[0].split("Return window")[0]
    q = re.sub(r"\(.*?\)", "", q)
    q = re.sub(r"\[.*?\]", "", q)
    q = re.sub(r"Vol\.\s*\d+.*", "", q, flags=re.IGNORECASE)
    q = re.sub(r"Includes Vols.*", "", q, flags=re.IGNORECASE)
    q = re.sub(r"\d+\s*oz.*", "", q, flags=re.IGNORECASE)
    q = re.sub(r"\d+\s*g\b.*", "", q, flags=re.IGNORECASE)
    q = re.sub(r"[,|/]", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q

def enrich_bakery_items():
    db = SessionLocal()
    fdc_service = FDCService(api_key="DEMO_KEY")

    try:
        bakery_cat = db.query(Category).filter(Category.name == "Bakery").first()
        if not bakery_cat:
            print("Bakery category not found.")
            return

        items = db.query(Item).filter(Item.category_id == bakery_cat.id).order_by(Item.name).all()
        print(f"Found {len(items)} items in Bakery category.\n")

        fdc_matched = 0
        off_matched = 0
        already_matched = 0
        unmatched = 0

        for idx, item in enumerate(items, start=1):
            name = item.name or ""
            print(f"[{idx}/{len(items)}] Processing: '{name}'")

            if item.fdc_id or item.off_code:
                already_matched += 1
                print(f"  ➜ Already matched (FDC: {item.fdc_id}, OFF: {item.off_code})")
                continue

            query = clean_item_name(name)
            print(f"  🔍 Cleaned Query: '{query}'")

            matched_this = False

            # 1. Try FDC search
            try:
                fdc_results = fdc_service.search_items(query)
                if fdc_results:
                    best = fdc_service.get_best_match(query, fdc_results, threshold=60)
                    if best:
                        fdc_id = best.get("fdcId")
                        gtin = best.get("gtinUpc")
                        ingredients = best.get("ingredients")
                        nutrients = fdc_service.extract_nutrients_100g(best)

                        item.fdc_id = fdc_id
                        if gtin and not item.gtin:
                            item.gtin = str(gtin)
                        if ingredients and not item.ingredients:
                            item.ingredients = ingredients
                        if nutrients and not item.nutrients:
                            item.nutrients = nutrients
                        item.nutrition_source = "fdc"

                        db.commit()
                        fdc_matched += 1
                        matched_this = True
                        desc = best.get("description", "")
                        brand = best.get("brandOwner") or best.get("brandName") or ""
                        print(f"  ✓ FDC MATCH (ID: {fdc_id}): '{brand} {desc}'. Nutrients: {len(nutrients)} fields.")
            except Exception as e:
                db.rollback()
                print(f"  ⚠ FDC lookup error: {e}")

            # 2. Try OpenFoodFacts if FDC didn't match
            if not matched_this:
                try:
                    off_res = OpenFoodFactsService.search_product(query, limit=3)
                    if off_res:
                        best_off = off_res[0]
                        code = best_off.get("code")
                        nutrients = best_off.get("nutrients", {})

                        item.off_code = code
                        if not item.gtin:
                            item.gtin = code
                        if best_off.get("image_url") and not item.image_url:
                            item.image_url = best_off.get("image_url")
                        if best_off.get("nutriscore") and not item.nutriscore:
                            item.nutriscore = best_off.get("nutriscore")
                        if nutrients and not item.nutrients:
                            item.nutrients = nutrients
                        item.nutrition_source = "openfoodfacts"

                        db.commit()
                        off_matched += 1
                        matched_this = True
                        print(f"  ✓ OFF MATCH (Code: {code}): '{best_off.get('brand')} {best_off.get('product_name')}'")
                except Exception as e:
                    db.rollback()
                    print(f"  ⚠ OFF lookup error: {e}")

            if not matched_this:
                unmatched += 1
                print("  ✗ No match found in FDC or OFF.")

            time.sleep(0.3)

        print("\n" + "="*50)
        print(f"Bakery Category Lookup Complete!")
        print(f"  Already matched: {already_matched}")
        print(f"  Newly matched via FDC: {fdc_matched}")
        print(f"  Newly matched via OFF: {off_matched}")
        print(f"  Remaining unmatched: {unmatched}")
        print("="*50)

    finally:
        db.close()

if __name__ == "__main__":
    enrich_bakery_items()
