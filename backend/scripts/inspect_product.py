import sys
from pathlib import Path

from sqlalchemy.orm import sessionmaker

# Add backend directory to path to import app modules
# Script is in backend/scripts, so we need parent (backend)
backend_path = Path(__file__).resolve().parent.parent
sys.path.append(str(backend_path))

from dotenv import load_dotenv

load_dotenv()

from app.database import engine
from app.models import Item, Receipt, ReceiptItem, Store


def inspect_product(search_term):
    Session = sessionmaker(bind=engine)
    session = Session()

    print(f"\nSearching for items matching: '{search_term}'\n")

    # Query
    results = (
        session.query(
            Item.name,
            Item.normalized_name,
            Store.name,
            Receipt.purchase_date,
            ReceiptItem.price,
            ReceiptItem.quantity,
        )
        .join(ReceiptItem, Item.id == ReceiptItem.item_id)
        .join(Receipt, ReceiptItem.receipt_id == Receipt.id)
        .join(Store, Receipt.store_id == Store.id)
        .filter(Item.name.ilike(f"%{search_term}%"))
        .order_by(Receipt.purchase_date.desc())
        .all()
    )

    if not results:
        print("No results found.")
        return

    # Header
    headers = ["Store", "Date", "Item Name (Alias)", "Normalized Name", "Price", "Qty"]
    col_widths = [20, 12, 40, 30, 10, 5]

    header_row = "".join(h.ljust(w) for h, w in zip(headers, col_widths, strict=False))
    print(header_row)
    print("-" * len(header_row))

    for row in results:
        item_name, norm_name, store_name, date, price, qty = row
        date_str = date.strftime("%Y-%m-%d") if date else "N/A"
        norm_name = norm_name or "-"

        print(
            f"{store_name[:19].ljust(20)}{date_str.ljust(12)}{item_name[:39].ljust(40)}{norm_name[:29].ljust(30)}${str(price).ljust(9)}{str(qty)}"
        )

    print(f"\nTotal matches: {len(results)}\n")
    session.close()


if __name__ == "__main__":
    term = "Athletic"
    if len(sys.argv) > 1:
        term = sys.argv[1]
    inspect_product(term)
