"""OCR evaluation harness — measure extraction accuracy against human-approved receipts.

Every reviewed receipt in the database is a labeled example: the saved
ReceiptItems are ground truth, and ocr_data holds the AI's original answer.

Modes:
  --stored (default)  Score the stored ocr_data against the approved items.
                      Zero API calls — instant accuracy baseline.
  --live              Re-run OCR on the receipt image with the CURRENT
                      backend/prompt and score that instead. Costs API/GPU
                      time; the OCR cache is keyed on image+prompt (not the
                      model), so move data/ocr_cache aside between models.

Corrections block (--live only):
  --corrections global  (default) the block a first-pass upload gets: the
                        receipt starts as Unknown Store, so all stores
  --corrections store   the block reprocessing gets, scoped to the saved store
  --corrections none    base prompt only, as --live sent before
  A receipt's own corrections are always left out of its block, or the model
  would be handed the answers it is being scored on.

Usage:
  uv run python scripts/ocr_eval.py                     # baseline, 15 receipts
  uv run python scripts/ocr_eval.py --receipt-ids 12 87 310
  uv run python scripts/ocr_eval.py --live --receipt-ids 12 87 310 --json out.json
  uv run python scripts/ocr_eval.py --live --corrections none --limit 5

--limit defaults to the number of --receipt-ids when ids are given, else 15.

Metrics per receipt:
  item_recall     labeled items the AI found (fuzzy name pairing)
  item_precision  AI items that correspond to a real labeled item
  name_score      mean name similarity across paired items (0-100), scored on
                  what the model read (original_ocr_name when auto-merge
                  renamed the line), so stored and live runs compare fairly
  price_acc       paired items whose final price matches within $0.01
  total_ok        receipt total within $0.05 of approved total
"""

import argparse
import json
import os
import sys
from collections.abc import Callable
from statistics import mean
from typing import Any

sys.path.append(os.getcwd())

from rapidfuzz import fuzz

PAIR_THRESHOLD = 55
DEFAULT_LIMIT = 15
CORRECTION_MODES = ("global", "store", "none")
METRICS = ("item_recall", "item_precision", "name_score", "price_acc", "total_ok")

Extractor = Callable[[str, str], dict]


def ai_name(ai: dict) -> str:
    """The name the model actually read.

    Stored ocr_data is saved after auto-merge renames a line to its catalog name,
    keeping the model's own read in ``original_ocr_name``. Scoring the catalog
    name would credit the stored run with a rename a live run never gets.
    """
    return (ai.get("original_ocr_name") or ai.get("name") or "").strip()


def pair_items(ai_items: list[dict], truth: list[tuple[str, float, float]]):
    """Greedy fuzzy pairing of AI lines to (name, price, qty) ground truth."""
    remaining = list(range(len(truth)))
    pairs, unmatched_ai = [], []
    for ai in ai_items:
        name = ai_name(ai)
        if not name:
            continue
        best_score, best_idx = 0.0, None
        for idx in remaining:
            score = fuzz.token_set_ratio(name.lower(), truth[idx][0].lower())
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
    name_scores = [fuzz.ratio(ai_name(ai).lower(), t[0].lower()) for ai, t in pairs]
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


def resolve_limit(limit: int | None, receipt_ids: list[int] | None) -> int:
    """An explicit --limit wins; otherwise every requested id, or the default."""
    if limit is not None:
        return limit
    return len(receipt_ids) if receipt_ids else DEFAULT_LIMIT


def build_prompt_extra(db, receipt, corrections: str) -> str:
    """The corrections block production would send for this receipt.

    ``global`` matches a first-pass upload, ``store`` matches reprocessing, and
    ``none`` sends the base prompt alone. Corrections come from the same input
    type as the receipt (image, PDF or paste), as in production, and the
    receipt's own corrections are always excluded.
    """
    if corrections == "none":
        return ""
    from app.services.correction_service import get_correction_prompt, input_type_of

    store_name = receipt.store.name if (corrections == "store" and receipt.store) else None
    return get_correction_prompt(
        db,
        store_name,
        exclude_receipt_ids=[receipt.id],
        input_type=input_type_of(receipt.image_path),
    )


def _production_extract(path: str, prompt_extra: str) -> dict:
    from app.services.ocr import process_pdf_receipt, process_receipt_image

    if path.lower().endswith(".pdf"):
        return process_pdf_receipt(path, prompt_extra)
    return process_receipt_image(path, prompt_extra)


def run_eval(
    db,
    *,
    receipt_ids: list[int] | None,
    limit: int,
    live: bool,
    corrections: str = "global",
    extract: Extractor | None = None,
) -> dict[str, Any]:
    """Score receipts; returns rows plus the receipts that could not be scored."""
    from app.models import Receipt

    extract = extract or _production_extract
    query = (
        db.query(Receipt)
        .filter(
            Receipt.status == "completed",
            Receipt.ocr_data.is_not(None),
            Receipt.image_path.is_not(None),
        )
        .order_by(Receipt.id.desc())
    )
    if receipt_ids:
        query = query.filter(Receipt.id.in_(receipt_ids))
    candidates = query.limit(limit * 3).all()

    rows: list[dict] = []
    errors: list[dict] = []
    unscored: list[int] = []
    for receipt in candidates:
        if len(rows) >= limit:
            break
        try:
            ai_data = json.loads(receipt.ocr_data)
        except (json.JSONDecodeError, TypeError):
            continue
        if ai_data.get("produce_mode") or (receipt.notes == "DEMO_DATA"):
            continue

        if live:
            path = receipt.image_path
            if not path or not os.path.exists(path):
                continue
            ai_data = extract(path, build_prompt_extra(db, receipt, corrections))
            if ai_data.get("error"):
                errors.append({"receipt_id": receipt.id, "error": str(ai_data["error"])})
                continue

        scored = score_receipt(ai_data, receipt)
        if scored:
            rows.append(scored)
        else:
            unscored.append(receipt.id)

    return {"rows": rows, "ocr_errors": errors, "unscored": unscored}


def summarize(rows: list[dict]) -> dict[str, float]:
    return {m: mean(r[m] for r in rows) for m in METRICS} if rows else {}


def print_table(result: dict[str, Any], mode_label: str) -> None:
    rows = result["rows"]
    print(f"\nOCR eval — {mode_label} — {len(rows)} receipts\n")
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
    means = summarize(rows)
    print(
        f"{'MEAN':>5} {'':<22} {'':>5} {'':>4} "
        f"{means['item_recall']:>7.0%} "
        f"{means['item_precision']:>6.0%} "
        f"{means['name_score']:>6.1f} "
        f"{means['price_acc']:>6.0%} "
        f"{means['total_ok']:>5.0%}"
    )
    if result["ocr_errors"]:
        ids = ", ".join(str(e["receipt_id"]) for e in result["ocr_errors"])
        print(f"\n{len(result['ocr_errors'])} OCR error(s), excluded from the mean: {ids}")
    if result["unscored"]:
        ids = ", ".join(str(i) for i in result["unscored"])
        print(f"{len(result['unscored'])} returned no items, excluded from the mean: {ids}")


def build_payload(result: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    return {
        "mode": "live" if args.live else "stored",
        "corrections": args.corrections if args.live else "as recorded",
        "backend": os.getenv("OCR_BACKEND"),
        "model": os.getenv("OCR_MODEL"),
        "requested_ids": args.receipt_ids,
        "mean": summarize(result["rows"]),
        "receipts": result["rows"],
        "ocr_errors": result["ocr_errors"],
        "unscored": result["unscored"],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--receipt-ids", type=int, nargs="*", default=None)
    parser.add_argument(
        "--live", action="store_true", help="Re-run OCR instead of scoring stored ocr_data"
    )
    parser.add_argument("--corrections", choices=CORRECTION_MODES, default="global")
    parser.add_argument(
        "--json", dest="json_path", default=None, help="Also write results to this file"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    # Loaded here rather than at import, so importing this module (tests) never
    # pulls the real .env into the environment.
    from dotenv import load_dotenv

    load_dotenv("../.env", override=True)
    from app.database import SessionLocal

    args = parse_args(argv)
    limit = resolve_limit(args.limit, args.receipt_ids)

    db = SessionLocal()
    try:
        result = run_eval(
            db,
            receipt_ids=args.receipt_ids,
            limit=limit,
            live=args.live,
            corrections=args.corrections,
        )
    finally:
        db.close()

    if not result["rows"]:
        print(
            "No scoreable receipts found (need completed receipts with ocr_data and saved items)."
        )
    else:
        mode = (
            f"LIVE re-extraction, corrections={args.corrections}"
            if args.live
            else "stored ocr_data (baseline)"
        )
        print_table(result, mode)

    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as fh:
            json.dump(build_payload(result, args), fh, indent=2)
        print(f"\nWrote {args.json_path}")


if __name__ == "__main__":
    main()
