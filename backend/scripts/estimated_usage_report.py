"""
estimated_usage_report.py
-------------------------
One-off estimate of which lessons *would* have been sent, before CM-07 (CM-14).

Usage logging started with CM-07. Everything before it is blank, so the
corrections page reports ``never`` for lessons that were in fact sent many
times. This replays the selection for each receipt uploaded since the first
correction was recorded and writes what it finds to a file.

**The output is an estimate and the report says so.** Two reasons it cannot be
history:

  1. ``ocr_corrections.created_at`` is the time the row was *written*, and
     re-saving a review deletes and re-writes that receipt's rows. On the live
     database 220 of 433 timestamps are more than a day after their receipt was
     uploaded, so the replay's clock is partly wrong: a lesson can look
     available earlier or later than it really was.
  2. Suppression and pins are applied as they stand now, not as of the moment
     being replayed. No history of those decisions exists.

So this answers "roughly how much has each lesson been earning its slot?"
It does not answer "what was receipt 412 actually prompted with?" — only the
usage log can, and only from CM-07 onward.

Writes a file. Never writes to ``correction_usage``. Run from backend/:

    uv run python scripts/estimated_usage_report.py

    --output PATH   where to write (default: data/estimated_usage_report.md)
    --limit N       prompt size to replay (default: CORRECTION_PROMPT_LIMIT)
    --top N         how many lessons to list (default 40)
    --stdout        print instead of writing a file
"""

import argparse
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models import OcrCorrection, Receipt, Store
from app.services.correction_service import (
    _correction_prompt_limit,
    _lesson_identity,
    input_type_of,
)

DEFAULT_OUTPUT = Path("data") / "estimated_usage_report.md"
RESAVE_THRESHOLD_DAYS = 1


def _pool_at(corrections: list[OcrCorrection], moment: datetime) -> list[OcrCorrection]:
    """Corrections that existed when this receipt was uploaded, newest first.

    ``corrections`` arrives sorted oldest first, so this walks back from the
    cut rather than re-sorting per receipt.
    """
    cut = 0
    for index, correction in enumerate(corrections):
        if correction.created_at and correction.created_at <= moment:
            cut = index + 1
        else:
            break
    return list(reversed(corrections[:cut]))


def _select(pool: list[OcrCorrection], store_id: int | None, kind: str, limit: int) -> list:
    """The same shape of selection the prompt block makes, without the database.

    Store first, falling back to every store within the input type, then
    distinct lessons up to the limit. Mirrors select_corrections; it is
    reimplemented here because that function reads the tables as they are now,
    and this has to read them as they were.
    """
    same_kind = [c for c in pool if (c.input_type or "") == kind]
    scoped = [c for c in same_kind if store_id is not None and c.store_id == store_id]
    chosen = scoped or same_kind

    seen: set[object] = set()
    kept = []
    for correction in chosen:
        identity = _lesson_identity(correction)
        if identity in seen:
            continue
        seen.add(identity)
        kept.append(correction)
        if len(kept) >= limit:
            break
    return kept


def build_report(db, limit: int, top: int) -> str:
    corrections = (
        db.query(OcrCorrection)
        .filter(OcrCorrection.created_at.isnot(None))
        .order_by(OcrCorrection.created_at)
        .all()
    )
    receipts = db.query(Receipt).filter(Receipt.created_at.isnot(None)).all()
    receipts.sort(key=lambda r: r.created_at)

    # OcrCorrection carries a bare store_id with no relationship, so names are
    # looked up once rather than per row.
    store_names = {store_id: name for store_id, name in db.query(Store.id, Store.name).all()}

    if not corrections:
        return "# Estimated correction usage\n\nNo corrections recorded.\n"

    first_correction = corrections[0].created_at
    replayed = [r for r in receipts if r.created_at >= first_correction]

    # How wrong the clock is: a correction recorded long after its receipt was
    # uploaded is a re-save, and its timestamp is not when the lesson was learnt.
    by_receipt = {r.id: r for r in receipts}
    resaves = 0
    for correction in corrections:
        receipt = by_receipt.get(correction.receipt_id)
        if receipt and receipt.created_at:
            lag = correction.created_at - receipt.created_at
            if lag.days >= RESAVE_THRESHOLD_DAYS:
                resaves += 1

    sends: Counter = Counter()
    described: dict[object, OcrCorrection] = {}
    empty_pool = 0
    per_receipt: list[tuple[int, int]] = []

    for receipt in replayed:
        pool = _pool_at(corrections, receipt.created_at)
        # A receipt's own corrections postdate its upload, so the cut already
        # excludes them; nothing here can hand a receipt its own answers.
        kind = input_type_of(receipt.image_path)
        chosen = _select(pool, receipt.store_id, kind, limit)
        if not chosen:
            empty_pool += 1
        per_receipt.append((receipt.id, len(chosen)))
        for correction in chosen:
            identity = _lesson_identity(correction)
            sends[identity] += 1
            described.setdefault(identity, correction)

    total_sends = sum(sends.values())
    lessons = {_lesson_identity(c) for c in corrections}
    never_sent = len(lessons) - len(sends)

    lines = [
        "# Estimated correction usage",
        "",
        f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} by "
        "`scripts/estimated_usage_report.py`.",
        "",
        "## This is an estimate",
        "",
        "Usage logging started with CM-07. This replays the selection for receipts",
        "uploaded before then, so it is a reconstruction, not a record.",
        "",
        f"- **{resaves} of {len(corrections)} correction timestamps are re-save times.**",
        "  `created_at` is when the row was written, and re-saving a review rewrites",
        "  that receipt's rows. The replay's clock is wrong for those, so a lesson can",
        "  appear available earlier or later than it truly was.",
        "- Suppression and pins are applied as they stand today, not as of the moment",
        "  being replayed. No history of those decisions exists.",
        "- Nothing here is written to `correction_usage`. That table only ever holds",
        "  real sends, from CM-07 onward.",
        "",
        "## What was replayed",
        "",
        f"- Prompt size: {limit} lessons",
        f"- Corrections in the log: {len(corrections)}, describing {len(lessons)} distinct lessons",
        f"- Receipts uploaded on or after the first correction: {len(replayed)}",
        f"- Receipts whose pool was empty at upload: {empty_pool}",
        f"- Estimated sends in total: {total_sends}",
        f"- Lessons never selected: {never_sent} of {len(lessons)}",
        "",
        f"## Most-sent lessons (top {top})",
        "",
        "| sends | store | input | field | correction |",
        "| ----: | ----- | ----- | ----- | ---------- |",
    ]

    for identity, count in sends.most_common(top):
        correction = described[identity]
        before = (correction.ai_value or "(missing)").replace("|", "\\|")
        after = (correction.approved_value or "(removed)").replace("|", "\\|")
        store = store_names.get(correction.store_id) or "Unknown Store"
        lines.append(
            f"| {count} | {store} | {correction.input_type or '—'} | "
            f"{correction.field} | {before} → {after} |"
        )

    lines += [
        "",
        "## Reading this",
        "",
        "A high count means the lesson occupied a prompt slot often, not that it",
        "helped. A lesson recorded again after it was already being sent is one that",
        "is not working — the corrections page flags those once real usage data",
        "accumulates.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Estimate correction usage before CM-07.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--top", type=int, default=40)
    parser.add_argument("--stdout", action="store_true", help="print instead of writing")
    args = parser.parse_args()

    limit = args.limit if args.limit is not None else _correction_prompt_limit()

    db = SessionLocal()
    try:
        report = build_report(db, limit=limit, top=args.top)
    finally:
        db.close()

    if args.stdout:
        print(report)
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"Wrote {args.output} ({len(report.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
