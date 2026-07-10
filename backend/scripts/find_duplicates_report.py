import os

from dotenv import load_dotenv

# Load env before importing app modules
load_dotenv(os.path.join(os.getcwd(), "..", ".env"))

from app.database import SessionLocal
from app.models import Receipt, ReceiptItem, Store


def find_duplicates():
    db = SessionLocal()
    try:
        # 1. Fetch all receipts with store names
        all_receipts = db.query(Receipt, Store.name).join(Store, Receipt.store_id == Store.id).all()

        # 2. Group by Normalized Store, Date, and Total
        potential_groups = {}
        for r, store_name in all_receipts:
            norm_store = store_name.strip().lower()
            date_str = r.purchase_date.strftime("%Y-%m-%d") if r.purchase_date else "None"
            # Use rounded total to avoid floating point issues during grouping
            key = (norm_store, date_str, round(float(r.total_amount), 2))

            if key not in potential_groups:
                potential_groups[key] = []
            potential_groups[key].append(r)

        print("--- DUPLICATE RECEIPT AUDIT REPORT ---\n")
        print("Format: store name | receipt ID | purchase date | item count | total\n")

        found_any = False
        for key, matches in potential_groups.items():
            if len(matches) < 2:
                continue

            found_any = True
            norm_store, date_str, total_val = key

            empty_receipts = []
            twin_receipts = []

            for r in matches:
                item_count = db.query(ReceiptItem).filter(ReceiptItem.receipt_id == r.id).count()
                # Get the actual store name used in this record
                actual_store = db.query(Store.name).filter(Store.id == r.store_id).scalar()

                r_data = {
                    "store": actual_store,
                    "id": r.id,
                    "date": date_str,
                    "count": item_count,
                    "total": f"${r.total_amount:.2f}",
                }

                if item_count == 0:
                    empty_receipts.append(r_data)
                else:
                    twin_receipts.append(r_data)

            # Print results for this group
            for info in empty_receipts:
                print(
                    f"{info['store']} | {info['id']} | {info['date']} | {info['count']} | {info['total']} (EMPTY)"
                )
            for info in twin_receipts:
                print(
                    f"{info['store']} | {info['id']} | {info['date']} | {info['count']} | {info['total']} (TWIN)"
                )
            print("-" * 20)

        if not found_any:
            print("No duplicates found based on Store/Date/Total (Case-Insensitive).")

    finally:
        db.close()


if __name__ == "__main__":
    # Ensure current directory is in sys.path for app imports
    import sys

    sys.path.append(os.getcwd())
    find_duplicates()
