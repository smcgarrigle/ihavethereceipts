import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.dirname(BASE_DIR)}/grocery.db"

from app.database import SessionLocal
from app.models import Item

db = SessionLocal()

bad_items = db.query(Item).filter(Item.name.like("Clean Name:%")).all()
print(f"Found {len(bad_items)} corrupted items.")

for item in bad_items:
    original = item.name
    cleaned = original.replace("Clean Name: ", "").replace("Clean Name:", "").strip()

    if not cleaned:
        cleaned = "Unknown Grocery Item"

    print(f"Fixing: '{original}' -> '{cleaned}'")
    item.name = cleaned
    item.normalized_name = cleaned.lower()

db.commit()
db.close()
print("Database repair complete.")
