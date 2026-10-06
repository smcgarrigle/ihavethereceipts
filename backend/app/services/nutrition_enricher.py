import logging
import threading
import time
from uuid import uuid4

from rapidfuzz import fuzz
from sqlalchemy import case, func, not_, or_

from app.api.trends_nutrition import _json_present
from app.database import SessionLocal
from app.models import Category, Item, ReceiptItem
from app.models.nutrition_suggestion import NutritionSuggestion
from app.services.fdc_service import fdc_service
from app.services.spend import LINE_TOTAL

logger = logging.getLogger(__name__)

# Categories to exclude from enrichable items
EXCLUDED_CATEGORIES = {"Fees & Taxes", "Household", "Health & Beauty", "Other"}


def get_enrichable_coverage(db) -> float:
    """
    Returns the percentage of enrichable items (excluding non-food) that have nutrients.
    """
    has_nutrients = or_(_json_present(Item.nutrients), _json_present(Item.custom_nutrients))

    query = (
        db.query(
            func.count(func.distinct(Item.id)).label("total_items"),
            func.count(func.distinct(case((has_nutrients, Item.id)))).label("covered_items"),
        )
        .outerjoin(Category, Item.category_id == Category.id)
        .filter(or_(Category.id.is_(None), not_(Category.name.in_(EXCLUDED_CATEGORIES))))
    )

    row = query.one()
    total = row.total_items or 0
    covered = row.covered_items or 0
    return (covered / total * 100.0) if total > 0 else 100.0


def get_uncovered_items(db, limit: int = 50):
    """
    Gets items that have no nutrition data and haven't been suggested in this run,
    prioritized by total spend across all receipts.
    """
    has_nutrients = or_(_json_present(Item.nutrients), _json_present(Item.custom_nutrients))

    # Compute total spend per item
    spend_subq = (
        db.query(ReceiptItem.item_id, func.coalesce(func.sum(LINE_TOTAL), 0.0).label("total_spend"))
        .group_by(ReceiptItem.item_id)
        .subquery()
    )

    query = (
        db.query(Item)
        .outerjoin(Category, Item.category_id == Category.id)
        .outerjoin(spend_subq, Item.id == spend_subq.c.item_id)
        .filter(not_(has_nutrients))
        .filter(or_(Category.id.is_(None), not_(Category.name.in_(EXCLUDED_CATEGORIES))))
        .order_by(spend_subq.c.total_spend.desc().nulls_last())
        .limit(limit)
    )
    return query.all()


def has_prior_suggestion(db, item_id: int) -> bool:
    """Check if we already suggested (and maybe rejected) this item."""
    return (
        db.query(NutritionSuggestion).filter(NutritionSuggestion.item_id == item_id).first()
        is not None
    )


class NutritionEnricher:
    """Background nutrition enrichment — searches FDC for uncovered items."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.worker_thread = None
        self._initialized = True
        logger.info("✓ NutritionEnricher service initialized")

    def start(self, batch_size: int = 50):
        """Spawn daemon thread to enrich up to batch_size items."""
        with self._lock:
            if self.worker_thread and self.worker_thread.is_alive():
                logger.info("[NutritionEnricher] Thread already running.")
                return

            self.worker_thread = threading.Thread(
                target=self._run_batch, args=(batch_size,), daemon=True
            )
            self.worker_thread.start()
            logger.info("🚀 NutritionEnricher worker thread started")

    def _run_batch(self, batch_size: int):
        """Core loop: find uncovered items, search FDC, store suggestions."""
        db = SessionLocal()
        batch_id = uuid4().hex[:12]

        try:
            # 1. Get uncovered items, ordered by spend descending
            uncovered = get_uncovered_items(db, limit=batch_size)

            if not uncovered:
                logger.info("[NutritionEnricher] No uncovered items found. Exiting.")
                return

            for item in uncovered:
                # Skip if already suggested
                if has_prior_suggestion(db, item.id):
                    continue

                if not item.name:
                    continue

                # 2. Search FDC
                enriched = fdc_service.enrich_item_data(item.name)
                if not enriched:
                    # Still need to record that we tried it to avoid infinite looping
                    suggestion = NutritionSuggestion(
                        item_id=item.id,
                        fdc_id=0,
                        fdc_description="[No match found]",
                        match_score=0.0,
                        nutrients={},
                        status="skipped",
                        batch_id=batch_id,
                    )
                    db.add(suggestion)
                    db.commit()
                    time.sleep(4)
                    continue

                # 3. Score the match
                cleaned_name = fdc_service._clean_query(item.name).lower()
                fdc_full_name = (
                    f"{enriched.get('brand', '')} {enriched.get('description', '')}".strip().lower()
                )

                score = fuzz.token_set_ratio(cleaned_name, fdc_full_name)

                # 4. Store as suggestion
                suggestion = NutritionSuggestion(
                    item_id=item.id,
                    fdc_id=enriched["fdc_id"],
                    fdc_description=enriched["description"],
                    fdc_brand=enriched.get("brand"),
                    match_score=score,
                    nutrients=enriched["nutrients"],
                    batch_id=batch_id,
                )
                db.add(suggestion)
                db.commit()

                # Rate limit: 4s between FDC calls
                time.sleep(4)
        except Exception as e:
            logger.error(f"[NutritionEnricher] Error in batch processing: {e}")
            db.rollback()
        finally:
            db.close()


# Global singleton
nutrition_enricher = NutritionEnricher()
