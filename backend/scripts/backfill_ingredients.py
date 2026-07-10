import os
import sys

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import SessionLocal
from app.models import Item
from app.services.fdc_service import fdc_service


def backfill_ingredients():
    db = SessionLocal()
    try:
        items = db.query(Item).filter(Item.fdc_id.isnot(None), Item.ingredients.is_(None)).all()
        print(f"Found {len(items)} items to backfill.")

        for item in items:
            print(f"Backfilling {item.name} (FDC ID: {item.fdc_id})...")
            details = fdc_service.get_food_details(item.fdc_id)
            if details and "ingredients" in details:
                item.ingredients = details["ingredients"]
                print("  - Added ingredients.")
            else:
                print("  - No ingredients found in USDA data.")

        db.commit()
        print("Backfill complete.")
    finally:
        db.close()


if __name__ == "__main__":
    backfill_ingredients()
