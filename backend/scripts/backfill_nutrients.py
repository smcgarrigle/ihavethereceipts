"""
Full nutrient backfill sweep — Phase 1 of the nutrition remediation plan.

Matches every item missing nutrient data against USDA FDC (primary) and
OpenFoodFacts (fallback), writing full per-100g nutrient payloads.

Design constraints:
  - Additive only: never overwrites existing nutrients/fdc_id/gtin values.
  - Checkpointed: progress persists to data/nutrient_backfill_checkpoint.json,
    so the sweep can be interrupted and resumed (e.g. run overnight in chunks).
  - Rate-limited: FDC allows 1,000 req/hr; default 4s delay stays safely under.

Usage:
  uv run python scripts/backfill_nutrients.py                 # full resumable sweep
  uv run python scripts/backfill_nutrients.py --limit 25      # small test batch
  uv run python scripts/backfill_nutrients.py --dry-run       # report, no writes
  uv run python scripts/backfill_nutrients.py --source off    # OpenFoodFacts only
  uv run python scripts/backfill_nutrients.py --reset         # clear checkpoint, start over
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

# Add current directory to path so we can import app
sys.path.append(os.getcwd())

from app.database import SessionLocal
from app.models.item import Item
from app.services.external_product import OpenFoodFactsService
from app.services.fdc_service import fdc_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_nutrients")

CHECKPOINT_FILE = Path("data/nutrient_backfill_checkpoint.json")


def load_checkpoint() -> dict:
    if CHECKPOINT_FILE.exists():
        try:
            return json.loads(CHECKPOINT_FILE.read_text())
        except Exception as e:
            logger.warning(f"Could not read checkpoint, starting fresh: {e}")
    return {"processed_ids": [], "matched": 0, "unmatched": 0}


def save_checkpoint(state: dict) -> None:
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_FILE.write_text(json.dumps(state))


def enrich_via_fdc(db, item: Item, dry_run: bool) -> bool:
    """FDC search → best match → full nutrient payload. Returns True on match."""
    enriched = fdc_service.enrich_item_data(item.name)
    if not enriched or not enriched.get("nutrients"):
        return False
    if dry_run:
        logger.info(f"  [dry-run] FDC match: {enriched['description']} ({enriched['fdc_id']})")
        return True
    # Additive writes only — fill blanks, never overwrite
    if not item.fdc_id:
        item.fdc_id = enriched["fdc_id"]
    if not item.gtin and enriched.get("gtin"):
        item.gtin = enriched["gtin"]
    if not item.ingredients and enriched.get("ingredients"):
        item.ingredients = enriched["ingredients"]
    if not item.nutrients:
        item.nutrients = enriched["nutrients"]
    db.commit()
    return True


def enrich_via_off(db, item: Item, dry_run: bool) -> bool:
    """OpenFoodFacts fallback (uses existing propagation-aware enrichment)."""
    if dry_run:
        result = OpenFoodFactsService.search_product(item.name, limit=1)
        matched = bool(result)
        if matched:
            logger.info(f"  [dry-run] OFF match: {result[0]['product_name']}")
        return matched
    return OpenFoodFactsService.enrich_db_item(db, item.id)


def backfill(limit: int | None, delay: float, source: str, dry_run: bool) -> None:
    state = load_checkpoint()
    processed = set(state["processed_ids"])

    db = SessionLocal()
    try:
        items = db.query(Item).filter(Item.nutrients.is_(None)).order_by(Item.id).all()
        pending = [i for i in items if i.id not in processed]
        logger.info(
            f"{len(items)} items missing nutrients; {len(pending)} not yet attempted "
            f"(checkpoint: {state['matched']} matched, {state['unmatched']} unmatched)"
        )

        attempted = 0
        for item in pending:
            if limit is not None and attempted >= limit:
                logger.info(f"Reached --limit {limit}, stopping. Re-run to continue.")
                break
            attempted += 1
            logger.info(f"[{attempted}/{limit or len(pending)}] #{item.id} {item.name}")

            matched = False
            if source in ("fdc", "both"):
                matched = enrich_via_fdc(db, item, dry_run)
            if not matched and source in ("off", "both"):
                matched = enrich_via_off(db, item, dry_run)

            state["matched" if matched else "unmatched"] += 1
            if not dry_run:
                state["processed_ids"].append(item.id)
                save_checkpoint(state)

            time.sleep(delay)

        logger.info(
            f"Done. Session: {attempted} attempted. "
            f"Cumulative: {state['matched']} matched, {state['unmatched']} unmatched."
        )
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill nutrient data for all items")
    parser.add_argument("--limit", type=int, default=None, help="Max items to attempt this run")
    parser.add_argument("--delay", type=float, default=4.0, help="Seconds between API calls")
    parser.add_argument(
        "--source", choices=["fdc", "off", "both"], default="both", help="Data source(s)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Report matches without writing")
    parser.add_argument("--reset", action="store_true", help="Clear checkpoint and start over")
    args = parser.parse_args()

    if args.reset and CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        logger.info("Checkpoint cleared.")

    backfill(args.limit, args.delay, args.source, args.dry_run)
