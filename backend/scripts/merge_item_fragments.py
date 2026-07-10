import json
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from backend/.env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

# Ensure backend folder is in path
sys.path.append(str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models import Item, Receipt, ReceiptItem


def merge_fragments():
    db = SessionLocal()

    # Fragments to look for (exact or suffix matches)
    fragments = [
        "Vary)",
        "May Vary)",
        "(Frozen)",
        "Ounce Box",
        "Packaging May Vary)",
        "Belly, Packaging May Vary)",
        "Driver tip:",
        "Brisbane, CA",
        "Kosher",
        "United States San Francisco",
        "(Previously",
    ]

    total_merged = 0

    try:
        receipts = db.query(Receipt).all()

        for r in receipts:
            # 1. Fetch all items for this receipt
            ri_items = (
                db.query(ReceiptItem)
                .filter(ReceiptItem.receipt_id == r.id)
                .order_by(ReceiptItem.id)
                .all()
            )
            if not ri_items:
                continue

            # 2. Identify parents and their fragments
            merges = []  # List of (parent_ri, [fragment_ri, ...])
            current_parent = None
            current_fragments = []

            for ri in ri_items:
                is_frag = any(f.lower() in ri.item.name.lower() for f in fragments) or (
                    len(ri.item.name) < 3 and ri.item.name.strip()
                )

                if is_frag and current_parent:
                    current_fragments.append(ri)
                else:
                    # If we had a previous set of fragments, save them
                    if current_parent and current_fragments:
                        merges.append((current_parent, current_fragments))

                    current_parent = ri
                    current_fragments = []

            # Catch the last set
            if current_parent and current_fragments:
                merges.append((current_parent, current_fragments))

            if not merges:
                continue

            print(f"Receipt {r.id}: Found {len(merges)} merge groups")

            for parent_ri, frags in merges:
                # Build new name and sum prices
                new_name = parent_ri.item.name
                total_price = float(parent_ri.price or 0)
                frag_ids = []

                for f in frags:
                    new_name += f" {f.item.name}"
                    total_price += float(f.price or 0)
                    frag_ids.append(f.id)

                new_name = new_name.strip()
                print(f"   Merging into: {new_name} (${total_price:.2f})")

                # Update Parent Item
                norm_name = new_name[:255].lower().strip()  # truncate if name too long
                merged_item = db.query(Item).filter(Item.normalized_name == norm_name).first()
                if not merged_item:
                    merged_item = Item(
                        name=new_name[:255],
                        normalized_name=norm_name,
                        category_id=parent_ri.item.category_id,
                    )
                    db.add(merged_item)
                    db.commit()
                    db.refresh(merged_item)

                parent_ri.item_id = merged_item.id
                parent_ri.price = total_price

                # Delete fragments
                db.query(ReceiptItem).filter(ReceiptItem.id.in_(frag_ids)).delete(
                    synchronize_session=False
                )
                total_merged += len(frags)

            db.commit()

            # 3. Sync ocr_data JSON
            db.refresh(r)
            receipt_items = db.query(ReceiptItem).filter(ReceiptItem.receipt_id == r.id).all()
            try:
                ocr_data = json.loads(r.ocr_data) if r.ocr_data else {}
            except:
                ocr_data = {}

            new_json_items = []
            for ri in receipt_items:
                item = db.query(Item).get(ri.item_id)
                new_json_items.append(
                    {
                        "name": item.name,
                        "final_price": float(ri.price) if ri.price else 0.0,
                        "quantity": float(ri.quantity) if ri.quantity else 1.0,
                        "category": item.category.name if item.category else "Other",
                    }
                )

            ocr_data["items"] = new_json_items
            r.ocr_data = json.dumps(ocr_data)
            db.commit()

        print(f"Successfully merged {total_merged} fragments.")

    except Exception as e:
        print(f"Error during fragment merge: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    merge_fragments()
