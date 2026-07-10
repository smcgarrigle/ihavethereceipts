"""Script to clean up specific boilerplate text from item names in the database."""

import os
import sys

# Add the backend directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session

from app.database import SessionLocal

TARGET_TEXT = "(Previously Amazon Fresh, Packaging May Vary)"


def clean_item_names():
    db: Session = SessionLocal()
    try:
        from app.models.item import Item

        items = db.query(Item).all()

        boilerplates = [
            "(Previously Amazon Fresh, Packaging May Vary)",
            "(Previously Amazon Fresh, Packaging may vary)",
            "(Previously Fresh Brand, Packaging May Vary)",
            "(Previously Fresh Brand, )",
            "(Previously H",
        ]

        cleaned_count = 0
        for item in items:
            old_name = item.name
            new_name = old_name
            for b in boilerplates:
                new_name = new_name.replace(b, "")

            new_name = new_name.strip()
            new_name = " ".join(new_name.split())

            if new_name != old_name:
                item.name = new_name
                print(f"Updated: '{old_name}' -> '{new_name}'")
                cleaned_count += 1

        db.commit()
        print(f"Successfully cleaned {cleaned_count} items.")
    finally:
        db.close()


if __name__ == "__main__":
    clean_item_names()
