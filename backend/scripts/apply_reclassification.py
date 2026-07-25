#!/usr/bin/env python3
import sys
from pathlib import Path

# Setup paths
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir / "backend"))

from dotenv import load_dotenv
load_dotenv(root_dir / "backend" / ".env")

from app.database import SessionLocal
from app.models import Category, Item
from generate_reclassification_analysis import classify_item

def apply_reclassifications():
    db = SessionLocal()
    try:
        other_cat = db.query(Category).filter(Category.name == "Other").first()
        if not other_cat:
            print("Error: 'Other' category not found.")
            return

        items = db.query(Item).filter(Item.category_id == other_cat.id).all()
        print(f"Found {len(items)} items currently in 'Other' category.")

        # Cache category name -> id mapping
        categories = {c.name: c for c in db.query(Category).all()}

        updated_count = 0
        skipped_count = 0

        for item in items:
            proposed_cat_name, conf = classify_item(item.name)
            if proposed_cat_name == "Other":
                skipped_count += 1
                continue

            target_cat = categories.get(proposed_cat_name)
            if not target_cat:
                target_cat = Category(name=proposed_cat_name)
                db.add(target_cat)
                db.flush()
                categories[proposed_cat_name] = target_cat

            item.category_id = target_cat.id
            updated_count += 1
            print(f"  ✓ '{item.name}' -> {proposed_cat_name} ({conf})")

        db.commit()
        print(f"\nSuccessfully reclassified {updated_count} items. Skipped {skipped_count} items.")
    except Exception as e:
        db.rollback()
        print(f"Error executing reclassification: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    apply_reclassifications()
