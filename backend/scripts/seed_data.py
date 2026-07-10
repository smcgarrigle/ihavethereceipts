import sys
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models import Category, Store

db = SessionLocal()

# Add stores (skip if exists)
store_names = ["Costco", "Safeway", "Trader Joe's"]
for store_name in store_names:
    existing = db.query(Store).filter(Store.name == store_name).first()
    if not existing:
        store = Store(name=store_name, address=f"{store_name} Location")
        db.add(store)
        print(f"✓ Added store: {store_name}")
    else:
        print(f"- Store already exists: {store_name}")

# Add categories (skip if exists)
category_names = [
    "Produce",
    "Dairy",
    "Meat",
    "Bakery",
    "Pantry",
    "Beverages",
    "Frozen",
    "Deli",
    "Health & Beauty",
    "Household",
    "Other",
]

for category_name in category_names:
    existing = db.query(Category).filter(Category.name == category_name).first()
    if not existing:
        category = Category(name=category_name)
        db.add(category)
        print(f"✓ Added category: {category_name}")
    else:
        print(f"- Category already exists: {category_name}")

db.commit()
print("\n✓ Seed data complete")
db.close()
