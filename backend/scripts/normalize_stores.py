import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add parent directory to path so we can import app modules
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.models import Store
from app.services.store_utils import normalize_store_name

# Database connection
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://grocery:grocery123@localhost:5433/grocery_tracker"
)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db = SessionLocal()


def main():
    print("=== Starting Store Normalization ===")

    stores = db.query(Store).all()
    print(f"Found {len(stores)} stores to process.")

    stores = db.query(Store).all()
    print(f"Found {len(stores)} stores to process.")

    # Group stores by their normalized name
    groups = {}
    for store in stores:
        norm_name = normalize_store_name(store.name)
        if norm_name not in groups:
            groups[norm_name] = []
        groups[norm_name].append(store)

    stores_to_delete = []

    # Process each group
    for norm_name, store_list in groups.items():
        # Sort so we keep the one that matches norm_name exactly, or just the first ID
        # Prefer exact match
        primary_store = None
        for s in store_list:
            if s.name == norm_name:
                primary_store = s
                break

        if not primary_store:
            primary_store = store_list[0]  # Pick the first one
            print(f"Renaming primary store '{primary_store.name}' -> '{norm_name}'")
            primary_store.name = norm_name

        # Merge others into primary
        for store in store_list:
            if store.id != primary_store.id:
                print(
                    f"Merging '{store.name}' into '{primary_store.name}' (ID: {store.id} -> {primary_store.id})"
                )
                for receipt in store.receipts:
                    receipt.store_id = primary_store.id
                stores_to_delete.append(store)

    # Commit changes
    try:
        # First commit the reassignments (and primary renames)
        db.commit()

        # Now delete the duplicate stores
        for store in stores_to_delete:
            db.delete(store)
        db.commit()

        print(f"Successfully processed stores. Deleted {len(stores_to_delete)} duplicates.")

    except Exception as e:
        print(f"Error during commit: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    main()
