import os
import sys

from dotenv import load_dotenv

# Load .env before importing SessionLocal
env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv(env_path)

# Add the backend directory to the path so we can import app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import or_

from app.database import SessionLocal
from app.models import Category, Item


def cleanup_junk_items():
    db = SessionLocal()
    try:
        # 1. Ensure 'Excluded' category exists
        excluded_cat = db.query(Category).filter(Category.name == "Excluded").first()
        if not excluded_cat:
            excluded_cat = Category(name="Excluded")
            db.add(excluded_cat)
            db.commit()
            db.refresh(excluded_cat)
            print(f"Created 'Excluded' category (ID: {excluded_cat.id})")
        else:
            print(f"Found 'Excluded' category (ID: {excluded_cat.id})")

        # 2. Define keywords for exclusion
        keywords = [
            "CRV",
            "CRV CRV",
            "CUSTOMER Service",
            "Revl Fruits",
            "Non-alcoholic",
            "Non alcoholic",
            "N/A Beer",
        ]

        # 3. Find items matching keywords
        query_filters = [Item.name.ilike(f"%{k}%") for k in keywords]
        items_to_exclude = db.query(Item).filter(or_(*query_filters)).all()

        print(f"Found {len(items_to_exclude)} items matching junk keywords.")

        # 4. Update items
        for item in items_to_exclude:
            if item.category_id != excluded_cat.id:
                print(f"  Excluding: {item.name}")
                item.category_id = excluded_cat.id

        # 5. Move items from 'Non-alcoholic beer' category if it exists
        na_cat = db.query(Category).filter(Category.name.ilike("%Non-alcoholic beer%")).first()
        if na_cat and na_cat.id != excluded_cat.id:
            na_items = db.query(Item).filter(Item.category_id == na_cat.id).all()
            print(f"Found {len(na_items)} items in '{na_cat.name}' category.")
            for item in na_items:
                item.category_id = excluded_cat.id

        db.commit()
        print("Cleanup complete.")

    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    cleanup_junk_items()
