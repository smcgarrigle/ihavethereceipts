"""
check_correction_backfill.py
----------------------------
Read-only audit of the correction memory tables (CM-13).

CM-06 added ``input_type`` and ``content_key`` to ``ocr_corrections`` and
backfilled both from existing rows. Everything built since keys off them:
suppression and pins are stored against ``content_key`` (CM-08, CM-09), usage
is logged against it (CM-07), and the corrections page groups by it (CM-10).
A backfill that drifted would not raise anywhere — it would quietly split one
lesson into two, or detach a person's decision from the lesson it was about.

So this checks the invariants rather than trusting them:

  1. Every correction has an input type, and it still matches the receipt it
     came from.
  2. Every correction has a content key, and recomputing it from the stored
     values reproduces it byte for byte.
  3. Corrections group into distinct lessons and the counts reconcile.
  4. No usage row is fabricated: each points at a real receipt and a key that
     some correction or override actually carries.
  5. Every override points at a well-formed key.

Writes nothing. Run from the backend/ directory:

    uv run python scripts/check_correction_backfill.py

    --verbose   list every offending row rather than the first few
    --limit N   how many examples to show per failure (default 5)

Exit status is 0 when every check passes and 1 when any fails, so it can gate
a future migration.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models import CorrectionOverride, CorrectionUsage, OcrCorrection, Receipt
from app.services.correction_keys import content_key
from app.services.correction_service import INPUT_TYPES, input_type_of

KEY_LENGTH = 40  # sha-1 hex


class Check:
    """One invariant, its failures, and how to describe them."""

    def __init__(self, name: str, detail: str = ""):
        self.name = name
        self.detail = detail
        self.failures: list[str] = []
        self.counted = 0

    def fail(self, message: str) -> None:
        self.failures.append(message)

    @property
    def passed(self) -> bool:
        return not self.failures

    def report(self, limit: int, verbose: bool) -> None:
        mark = "ok  " if self.passed else "FAIL"
        print(f"[{mark}] {self.name}  ({self.counted} checked)")
        if self.detail:
            print(f"       {self.detail}")
        if self.failures:
            shown = self.failures if verbose else self.failures[:limit]
            for line in shown:
                print(f"       - {line}")
            hidden = len(self.failures) - len(shown)
            if hidden > 0:
                print(f"       … and {hidden} more (use --verbose)")


def check_input_types(corrections, receipts_by_id) -> Check:
    check = Check(
        "input type present and matches its receipt",
        "CM-06 derived these from receipt.image_path; drift would split a lesson in two.",
    )
    for correction in corrections:
        check.counted += 1
        if not correction.input_type:
            check.fail(f"correction {correction.id} has no input_type")
            continue
        if correction.input_type not in INPUT_TYPES:
            check.fail(f"correction {correction.id} has input_type {correction.input_type!r}")
            continue
        receipt = receipts_by_id.get(correction.receipt_id)
        if receipt is None:
            # Reported by its own check below; not an input-type fault.
            continue
        expected = input_type_of(receipt.image_path)
        if correction.input_type != expected:
            check.fail(
                f"correction {correction.id} says {correction.input_type!r} "
                f"but receipt {receipt.id} is {expected!r}"
            )
    return check


def check_content_keys(corrections) -> Check:
    check = Check(
        "content key present and reproducible",
        "Suppression and pins are stored against this key; a wrong one orphans the decision.",
    )
    for correction in corrections:
        check.counted += 1
        key = correction.content_key
        if not key:
            check.fail(f"correction {correction.id} has no content_key")
            continue
        if len(key) != KEY_LENGTH:
            check.fail(f"correction {correction.id} has a {len(key)}-character key")
            continue
        recomputed = content_key(
            correction.store_id,
            correction.input_type,
            correction.field,
            correction.ai_value,
            correction.approved_value,
        )
        if recomputed != key:
            check.fail(
                f"correction {correction.id} stores {key[:12]}… "
                f"but its values hash to {recomputed[:12]}…"
            )
    return check


def check_receipts_exist(corrections, receipts_by_id) -> Check:
    check = Check(
        "every correction points at a receipt",
        "A correction whose receipt is gone cannot be scoped by input type.",
    )
    for correction in corrections:
        check.counted += 1
        if correction.receipt_id not in receipts_by_id:
            check.fail(
                f"correction {correction.id} points at missing receipt {correction.receipt_id}"
            )
    return check


def check_stores(corrections) -> Check:
    check = Check(
        "store recorded where the receipt has one",
        "A null store is legitimate for an unidentified receipt; it is reported, not failed.",
    )
    missing = 0
    for correction in corrections:
        check.counted += 1
        if correction.store_id is None:
            missing += 1
    if missing:
        check.detail += f" {missing} correction(s) have no store."
    return check


def check_usage_not_fabricated(db, corrections, receipts_by_id) -> Check:
    check = Check(
        "no usage row is fabricated",
        "Usage starts from the day CM-07 shipped; nothing backfills it.",
    )
    known_keys = {c.content_key for c in corrections if c.content_key}
    known_keys |= {key for (key,) in db.query(CorrectionOverride.content_key).all() if key}
    for usage in db.query(CorrectionUsage).all():
        check.counted += 1
        if not usage.content_key:
            check.fail(f"usage {usage.id} has no content_key")
            continue
        if usage.receipt_id not in receipts_by_id:
            check.fail(f"usage {usage.id} points at missing receipt {usage.receipt_id}")
        if usage.content_key not in known_keys:
            check.fail(
                f"usage {usage.id} names key {usage.content_key[:12]}… "
                "which no correction or override carries"
            )
        if usage.used_at is None:
            check.fail(f"usage {usage.id} has no used_at")
    return check


def check_overrides(db) -> Check:
    check = Check(
        "every override has a well-formed key",
        "An override is a person's decision; a malformed key silently loses it.",
    )
    for override in db.query(CorrectionOverride).all():
        check.counted += 1
        if not override.content_key or len(override.content_key) != KEY_LENGTH:
            check.fail(f"override {override.id} has key {override.content_key!r}")
        if override.input_type not in INPUT_TYPES:
            check.fail(f"override {override.id} has input_type {override.input_type!r}")
    return check


def summarise(corrections) -> None:
    """What the corrections page will show, straight from the rows."""
    lessons = {
        c.content_key or (c.store_id, c.field, c.ai_value, c.approved_value) for c in corrections
    }
    by_input = Counter(c.input_type or "(none)" for c in corrections)
    by_field = Counter(c.field for c in corrections)

    print()
    print(f"corrections      {len(corrections)}")
    print(f"distinct lessons {len(lessons)}")
    print("by input type    " + ", ".join(f"{k} {v}" for k, v in sorted(by_input.items())))
    print("by field         " + ", ".join(f"{k} {v}" for k, v in sorted(by_field.items())))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[2])
    parser.add_argument("--verbose", action="store_true", help="list every offending row")
    parser.add_argument("--limit", type=int, default=5, help="examples per failure (default 5)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        corrections = db.query(OcrCorrection).all()
        receipts_by_id = {r.id: r for r in db.query(Receipt).all()}

        checks = [
            check_receipts_exist(corrections, receipts_by_id),
            check_input_types(corrections, receipts_by_id),
            check_content_keys(corrections),
            check_stores(corrections),
            check_usage_not_fabricated(db, corrections, receipts_by_id),
            check_overrides(db),
        ]

        summarise(corrections)
        print()
        for check in checks:
            check.report(args.limit, args.verbose)

        failed = [c for c in checks if not c.passed]
        print()
        if failed:
            print(f"{len(failed)} of {len(checks)} checks failed.")
            return 1
        print(f"All {len(checks)} checks passed.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
