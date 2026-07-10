"""OCR evaluation harness — measure extraction accuracy against human-approved receipts.

Every reviewed receipt in the database is a labeled example: the saved
ReceiptItems are ground truth, and ocr_data holds the AI's original answer.

Modes:
  --stored (default)  Score the stored ocr_data against the approved items.
                      Zero API calls — instant accuracy baseline.
  --live              Re-run OCR on the receipt image with the CURRENT
                      backend/prompt and score that instead. Costs API/GPU
                      time; the OCR cache is keyed on image+prompt, so prompt
                      changes are evaluated for real.

Usage:
  uv run python scripts/ocr_eval.py                     # baseline, 15 receipts
  uv run python scripts/ocr_eval.py --limit 50
  uv run python scripts/ocr_eval.py --receipt-ids 12 87 310
  uv run python scripts/ocr_eval.py --live --limit 5

Metrics per receipt:
  item_recall     labeled items the AI found (fuzzy name pairing)
  item_precision  AI items that correspond to a real labeled item
  name_score      mean name similarity across paired items (0-100)
  price_acc       paired items whose final price matches within $0.01
  total_ok        receipt total within $0.05 of approved total
"""

import argparse
import json
import os
import sys
from statistics import mean

sys.path.append(os.getcwd())

from dotenv import load_dotenv

load_dotenv("../.env", override=True)

from rapidfuzz import fuzz

from app.database import SessionLocal
from app.models import Receipt

PAIR_THRESHOLD = 55


def pair_items(ai_items: list[dict], truth: list[tuple[str, float, float]]):
    """Greedy fuzzy pairing of AI lines to (name, price, qty) ground truth."""
    remaining = list(range(len(truth)))
    pairs, unmatched_ai = [], []
    for ai in ai_items:
        ai_name = (ai.get("name") or "").strip()
        if not ai_name:
            continue
        best_score, best_idx = 0.0, None
        for idx in remaining:
            score = fuzz.token_set_ratio(ai_name.lower(), truth[idx][0].lower())
            ai_price = ai.get("final_price")
            if ai_price is not None and abs(ai_price - truth[idx][1]) < 0.01:
                score += 15
            if score > best_score:
                best_score, best_idx = score, idx
        if best_idx is not None and best_score >= PAIR_THRESHOLD:
            pairs.append((ai, truth[best_idx]))
            remaining.remove(best_idx)
        else:
            unmatched_ai.append(ai)
    return pairs, unmatched_ai, [truth[i] for i in remaining]


def score_receipt(ai_data: dict, receipt) -> dict | None:
    truth = [
        (ri.item.name, round(ri.price * ri.quantity, 2), ri.quantity)
        for ri in receipt.items
        if ri.item
    ]
    ai_items = ai_data.get("items") or []
    if not truth or not ai_items:
        return None

    pairs, unmatched_ai, missed = pair_items(ai_items, truth)
    name_scores = [fuzz.ratio((ai.get("name") or "").lower(), t[0].lower()) for ai, t in pairs]
    price_hits = [
        1 if ai.get("final_price") is not None and abs(ai["final_price"] - t[1]) < 0.01 else 0
        for ai, t in pairs
    ]
    ai_total = ai_data.get("total_amount")
    return {
        "receipt_id": receipt.id,
        "store": receipt.store.name if receipt.store else "?",
        "n_truth": len(truth),
        "n_ai": len(ai_items),
        "item_recall": len(pairs) / len(truth),
        "item_precision": len(pairs) / len(ai_items) if ai_items else 0.0,
        "name_score": mean(name_scores) if name_scores else 0.0,
        "price_acc": mean(price_hits) if price_hits else 0.0,
        "total_ok": (
            1
            if ai_total is not None
            and receipt.total_amount is not None
            and abs(ai_total - receipt.total_amount) <= 0.05
            else 0
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--receipt-ids", type=int, nargs="*", default=None)
    parser.add_argument("--live", action="store_true", help="Re-run OCR instead of scoring stored ocr_data")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        query = (
            db.query(Receipt)
            .filter(
                Receipt.status == "completed",
                Receipt.ocr_data.is_not(None),
                Receipt.image_path.is_not(None),
            )
            .order_by(Receipt.id.desc())
        )
        if args.receipt_ids:
            query = query.filter(Receipt.id.in_(args.receipt_ids))
        candidates = query.limit(args.limit * 3).all()

        rows = []
        for receipt in candidates:
            if len(rows) >= args.limit:
                break
            try:
                ai_data = json.loads(receipt.ocr_data)
            except (json.JSONDecodeError, TypeError):
                continue
            if ai_data.get("produce_mode") or (receipt.notes == "DEMO_DATA"):
                continue

            if args.live:
                from app.services.ocr import process_pdf_receipt, process_receipt_image

                path = receipt.image_path
                if not path or not os.path.exists(path):
                    continue
                ai_data = (
                    process_pdf_receipt(path)
                    if path.lower().endswith(".pdf")
                    else process_receipt_image(path)
                )
                if ai_data.get("error"):
                    print(f"  receipt {receipt.id}: OCR error — {ai_data['error']}")
                    continue

            scored = score_receipt(ai_data, receipt)
            if scored:
                rows.append(scored)

        if not rows:
            print("No scoreable receipts found (need completed receipts with ocr_data and saved items).")
            return

        mode = "LIVE re-extraction" if args.live else "stored ocr_data (baseline)"
        print(f"\nOCR eval — {mode} — {len(rows)} receipts\n")
        hdr = f"{'id':>5} {'store':<22} {'truth':>5} {'ai':>4} {'recall':>7} {'prec':>6} {'name':>6} {'price':>6} {'total':>5}"
        print(hdr)
        print("-" * len(hdr))
        for r in rows:
            print(
                f"{r['receipt_id']:>5} {r['store'][:22]:<22} {r['n_truth']:>5} {r['n_ai']:>4} "
                f"{r['item_recall']:>7.0%} {r['item_precision']:>6.0%} {r['name_score']:>6.1f} "
                f"{r['price_acc']:>6.0%} {'  ok' if r['total_ok'] else 'MISS':>5}"
            )
        print("-" * len(hdr))
        print(
            f"{'MEAN':>5} {'':<22} {'':>5} {'':>4} "
            f"{mean(r['item_recall'] for r in rows):>7.0%} "
            f"{mean(r['item_precision'] for r in rows):>6.0%} "
            f"{mean(r['name_score'] for r in rows):>6.1f} "
            f"{mean(r['price_acc'] for r in rows):>6.0%} "
            f"{mean(r['total_ok'] for r in rows):>5.0%}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
