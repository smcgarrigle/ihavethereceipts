import os
import sys

sys.path.append(os.getcwd())
try:
    from app.database import SessionLocal
    from app.models import Receipt

    db = SessionLocal()
    receipts = db.query(Receipt).order_by(Receipt.id.desc()).all()

    # Write to a markdown file
    with open("all_receipts.md", "w") as f:
        f.write("# All Receipts\n\n")
        f.write("| ID | Store | Total | Purchase Date | Status | Review Link |\n")
        f.write("|---|---|---|---|---|---|\n")
        for r in receipts:
            store_name = r.store.name if r.store else "Unknown"
            date_str = r.purchase_date.strftime("%Y-%m-%d %H:%M") if r.purchase_date else "None"
            total = f"${r.total_amount:.2f}" if r.total_amount is not None else "$0.00"
            link = f"[Review #{r.id}](http://127.0.0.1:8000/receipts/{r.id}/review)"
            f.write(f"| {r.id} | {store_name} | {total} | {date_str} | {r.status} | {link} |\n")

    print("Done writing to all_receipts.md")
except Exception as e:
    print(f"Error: {e}")
