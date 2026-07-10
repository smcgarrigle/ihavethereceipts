import sys
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from backend/.env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

# Ensure backend folder is in path
sys.path.append(str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models import Category, Item


def auto_categorize():
    db = SessionLocal()

    # Mapping of keywords to Category Name
    # We use lowercase for comparison
    mappings = {
        "Produce (fruits, vegetables)": [
            "Apple",
            "Banana",
            "Lettuce",
            "Grapes",
            "Carrot",
            "Onion",
            "Mango",
            "Produce",
            "Cauliflower",
            "Tomato",
            "Cucumber",
        ],
        "Dairy": ["Milk", "Cheese", "Yogurt", "Chobani", "Butter"],
        "Meat": ["Chicken", "Beef", "Roast", "Meat", "Steak", "Pork", "Turkey"],
        "Beverages": ["Soda", "Water", "Juice", "LaCroix", "Coffee"],
        "Kombucha": ["Kombucha", "KEVITA", "Brew Dr"],
        "Non-Alcoholic Beer": ["IPA", "Non-Alcoholic Beer", "Athletic Brewing"],
        "Bakery": ["Baguette", "SEMIFREDDI", "Bread", "Sourdough"],
        "Alcohol": ["Wine", "Beer", "Whiskey", "Vodka"],
        "Household": ["Detergent", "Soap", "Paper Towel", "Toilet Paper"],
        "CRV (tax)": ["CRV"],
    }

    # Get category objects
    categories_by_name = {c.name: c for c in db.query(Category).all()}
    other_cat = categories_by_name.get("Other")

    if not other_cat:
        print("Could not find 'Other' category. Exiting.")
        return

    updated_count = 0

    try:
        # Get all items in 'Other'
        other_items = db.query(Item).filter(Item.category_id == other_cat.id).all()

        for item in other_items:
            for cat_name, keywords in mappings.items():
                target_cat = categories_by_name.get(cat_name)
                if not target_cat:
                    continue

                # Check if any keyword matches the item name
                if any(kw.lower() in item.name.lower() for kw in keywords):
                    item.category_id = target_cat.id
                    updated_count += 1
                    break  # Move to next item once categorized

        db.commit()
        print(f"Successfully re-categorized {updated_count} items from 'Other'.")

    except Exception as e:
        print(f"Error during categorization: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    auto_categorize()
