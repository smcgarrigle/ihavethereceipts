import argparse
import os
import sys

from dotenv import load_dotenv

# Add backend to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load env vars
load_dotenv()

import logging

from app.database import SessionLocal
from app.models import Receipt
from app.services.ocr import process_receipt_task
from app.services.receipt_claim import claim_receipt

# Configure logging to show progress in the terminal
logging.basicConfig(level=logging.INFO, format="Progress: %(message)s")


def main():
    parser = argparse.ArgumentParser(description="Reprocess OCR for a given receipt ID.")
    parser.add_argument("receipt_id", type=int, help="The ID of the receipt in the database.")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        receipt = db.query(Receipt).filter(Receipt.id == args.receipt_id).first()
        if not receipt:
            print(f"Error: Receipt with ID {args.receipt_id} not found.")
            sys.exit(1)

        print(f"--- Reprocessing Receipt {args.receipt_id} ---")
        print(f"Store: {receipt.store.name if receipt.store else 'Unknown'}")
        print(f"Image Path: {receipt.image_path}")

        if not receipt.image_path or not os.path.exists(receipt.image_path):
            print(f"Error: Image file not found at {receipt.image_path}")
            sys.exit(1)

        # Trigger the same task used by the background worker. Claim the row
        # first, whatever state it is in, so this manual run owns it.
        print("\nStarting OCR processing...")
        claim_receipt(db, receipt.id, force=True)
        process_receipt_task(receipt.id, receipt.image_path, claimed=True)

        # Refresh and show result
        db.refresh(receipt)
        print(f"\nStatus: {receipt.status}")
        if receipt.status == "completed":
            print(f"Success! New Total: ${receipt.total_amount}")
        else:
            print(f"Failed: {receipt.error_message}")

    except Exception as e:
        print(f"Unexpected error: {e}")
        import traceback

        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    main()
