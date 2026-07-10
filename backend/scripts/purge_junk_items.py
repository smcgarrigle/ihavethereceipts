import sys
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from backend/.env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

# Ensure backend folder is in path
sys.path.append(str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models import Item, ReceiptItem


def purge_junk():
    db = SessionLocal()

    # Patterns that identify junk rows
    junk_patterns = [
        "%Return window%",
        "%Return or replace %",
        "%Return items: Eligible%",
        "%Visa x%",
        "%Visa *%",
        "%Sold by:%",
        "%Supplied by:%",
        "%List Price:%",
        "%eligible:%",
        "%Payment method%",
        "%Write a Review%",
    ]

    deleted_count = 0

    try:
        # Find all items matching junk patterns
        for pattern in junk_patterns:
            items_to_purge = db.query(Item).filter(Item.name.like(pattern)).all()
            for item in items_to_purge:
                # Delete receipt items linked to this junk item
                res = db.query(ReceiptItem).filter(ReceiptItem.item_id == item.id).delete()
                deleted_count += res

                # We optionally delete the item itself if it has no more links
                # But for now, just removing the receipt links is enough to fix the totals.

        db.commit()
        print(f"Successfully purged {deleted_count} junk receipt items.")

    except Exception as e:
        print(f"Error during purge: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    purge_junk()
