import logging
import os
from typing import Any

import requests
from dotenv import load_dotenv
from rapidfuzz import fuzz

load_dotenv()

logger = logging.getLogger(__name__)

FDC_API_KEY = os.getenv("FDC_API_KEY")
FDC_BASE_URL = "https://api.nal.usda.gov/fdc/v1"


class FDCService:
    def __init__(self, api_key: str | None = FDC_API_KEY):
        self.api_key = api_key
        self.session = requests.Session()

    def _clean_query(self, query: str) -> str:
        """Strip OCR noise, store names, and measurements to improve search matching."""
        import re

        # 1. Lowercase and strip
        q = query.lower().strip()
        # Remove parenthetical details
        q = re.sub(r"\([^)]*\)", " ", q)

        # 2. Remove common OCR prefixes (e.g., "2@", "1@", "2X")
        q = re.sub(r"^\d+\s*[@x]\s*", "", q)

        # 3. Remove known store names and house brands (case-insensitive)
        store_patterns = [
            r"365 by whole foods market,?\s*",
            r"whole foods market,?\s*",
            r"365wfm\s*",
            r"safeway select\s*",
            r"kirkland signature\s*",
            r"trader joe\'s\s*",
        ]
        for pattern in store_patterns:
            q = re.sub(pattern, "", q)

        # 4. Remove large numeric IDs (likely SKUs or internal UPCs)
        q = re.sub(r"\b\d{7,}\b", "", q)

        # 5. Remove common measurements (e.g., "12 fl oz", "16oz", "32 ounce", "lb")
        q = re.sub(r"\b\d+\s*(fl\s*oz|oz|ounce|lb|g|kg|l|ml|ct|pk)\b", "", q)

        # 6. Expand common abbreviations
        abbreviation_map = {
            r"\bgrk\b": "greek",
            r"\bygrt\b": "yogurt",
            r"\byog\b": "yogurt",
            r"\bckn\b": "chicken",
            r"\bb/s\b": "boneless skinless",
            r"\bb/i\b": "bone in",
            r"\bat[ \.]?na\b": "athena",
            r"\bvty\b": "variety",
            r"\bgrnd\b": "ground",
            r"\borg\b": "organic",
            r"\bog\b": "organic",
            r"\bicd\b": "iced",
            r"\bjc\b": "juice",
            r"\bpch\b": "peach",
            r"\bkmbcha\b": "kombucha",
            r"\bkombuch\b": "kombucha",
            r"\bdrscl\b": "driscoll's",
            r"\bshrmp\b": "shrimp",
            r"\bbrst\b": "breast",
            r"\bbby\b": "baby",
            r"\bsmk\b": "smoked",
            r"\bsmked\b": "smoked",
            r"\bchdr\b": "cheddar",
            r"\bmozz\b": "mozzarella",
            r"\bmozzrella\b": "mozzarella",
            r"\brstd\b": "roasted",
            r"\bgrlc\b": "garlic",
            r"\bmtbl\b": "meatball",
            r"\bmtblls\b": "meatballs",
            r"\bna\b": "non alcoholic",
        }
        for abbr, full in abbreviation_map.items():
            q = re.sub(abbr, full, q)

        # 7. Remove product item codes (e.g. BTA-12121, ENZ-13051)
        q = re.sub(r"\b[a-z]{2,5}-\d{3,8}\b", "", q)

        # 8. Final cleanup: strip non-alphanumeric special characters, multiple spaces
        q = re.sub(r"[^\w\s]", " ", q)
        q = re.sub(r"\s+", " ", q).strip()

        # 9. Cap length to 80 chars to avoid FDC 400 Bad Request
        if len(q) > 80:
            q = q[:80].rsplit(" ", 1)[0]

        return q

    def search_items(
        self, query: str, data_type: list[str] | None = None, page_size: int = 10
    ) -> list[dict[str, Any]]:
        """Search for items in USDA FDC."""
        if data_type is None:
            data_type = ["Branded", "Foundation", "SR Legacy"]
        if not self.api_key:
            logger.warning("FDC_API_KEY not set")
            return []

        cleaned_query = self._clean_query(query)
        if not cleaned_query:
            return []

        url = f"{FDC_BASE_URL}/foods/search"
        params = {"api_key": self.api_key}
        # Annotated rather than inferred: the mixed value types would otherwise
        # infer as dict[str, object], which requests' JsonType rejects.
        payload: dict[str, Any] = {
            "query": cleaned_query,
            "dataType": data_type,
            "pageSize": page_size,
            "sortBy": "score",
        }

        try:
            response = self.session.post(url, params=params, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            return list(data.get("foods", []))
        except Exception as e:
            logger.error(f"Error searching FDC for '{query}': {e}")
            return []

    def get_food_details(self, fdc_id: int) -> dict[str, Any] | None:
        """Get full food details by FDC ID."""
        if not self.api_key:
            return None

        url = f"{FDC_BASE_URL}/food/{fdc_id}"
        params = {"api_key": self.api_key}

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            return dict(response.json())
        except Exception as e:
            logger.error(f"Error fetching FDC details for {fdc_id}: {e}")
            return None

    def get_best_match(
        self, query: str, items: list[dict[str, Any]], threshold: int = 60
    ) -> dict[str, Any] | None:
        """Find the best fuzzy match from a list of FDC items."""
        if not items:
            return None

        cleaned = self._clean_query(query)
        scored_items: list[dict[str, Any]] = []
        for item in items:
            description = item.get("description", "")
            brand = item.get("brandOwner", item.get("brandName", ""))

            # Combine brand and description for matching
            full_name = f"{brand} {description}".strip()

            # Use multiple matching strategies against cleaned and raw query
            score_token_set_cleaned = fuzz.token_set_ratio(cleaned.lower(), full_name.lower())
            score_partial_cleaned = fuzz.partial_ratio(cleaned.lower(), full_name.lower())
            score_token_set_raw = fuzz.token_set_ratio(query.lower(), full_name.lower())

            # Weighted / best score calculation
            final_score = max(
                (score_token_set_cleaned * 0.7) + (score_partial_cleaned * 0.3),
                score_token_set_raw,
                score_token_set_cleaned,
            )

            scored_items.append({"score": final_score, "item": item})

        scored_items.sort(key=lambda x: float(str(x["score"])), reverse=True)
        best = scored_items[0]

        if float(str(best["score"])) >= threshold:
            return dict(best["item"])

        return None

    # FDC nutrient number → the per-100g key used across the app (OFF-style)
    NUTRIENT_NUMBER_MAP = {
        "208": "energy-kcal_100g",
        "203": "proteins_100g",
        "204": "fat_100g",
        "205": "carbohydrates_100g",
        "269": "sugars_100g",
        "291": "fiber_100g",
        "307": "sodium_100g",  # FDC reports mg; converted to g below
        "606": "saturated-fat_100g",
    }

    @classmethod
    def extract_nutrients_100g(cls, food: dict[str, Any]) -> dict[str, float]:
        """
        Map an FDC food payload's nutrient list to the app's per-100g nutrient keys.
        Handles both the search-result shape ({nutrientNumber, value}) and the
        detail-endpoint shape ({nutrient: {number}, amount}). Branded FDC values
        are already per 100g/100ml.
        """
        nutrients: dict[str, float] = {}
        for n in food.get("foodNutrients", []):
            number = str(n.get("nutrientNumber") or (n.get("nutrient") or {}).get("number") or "")
            key = cls.NUTRIENT_NUMBER_MAP.get(number)
            if not key:
                continue
            value = n.get("value", n.get("amount"))
            if value is None:
                continue
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
            if key == "sodium_100g":
                value = value / 1000.0  # mg → g, matching the OFF convention
            nutrients[key] = value
        return nutrients

    def enrich_item_data(self, query: str) -> dict[str, Any] | None:
        """Search and return enriched data for a query."""
        results = self.search_items(query)
        best = self.get_best_match(query, results)

        if not best:
            return None

        return {
            "fdc_id": best.get("fdcId"),
            "description": best.get("description"),
            "brand": best.get("brandOwner") or best.get("brandName"),
            "category": best.get("foodCategory"),
            "gtin": best.get("gtinUpc"),
            "serving_size": best.get("servingSize"),
            "serving_unit": best.get("servingSizeUnit"),
            "ingredients": best.get("ingredients"),
            "nutrients": self.extract_nutrients_100g(best),
        }

    def enrich_db_item(self, db, item_id: int) -> bool:
        """Enrich an item in the database using FDC data, and propagate to similar items."""
        from app.models.item import Item

        db_item = db.query(Item).filter(Item.id == item_id).first()
        if not db_item:
            return False

        # Already enriched?
        if db_item.fdc_id:
            logger.info(
                f"Item '{db_item.name}' already has FDC data, but re-enriching to ensure propagation..."
            )

        enriched_data = self.enrich_item_data(db_item.name)
        if not enriched_data:
            return False

        try:
            # 1. Establish the Canonical Category
            category_id = None
            if enriched_data["category"]:
                from app.models.category import Category
                from app.services.category_mapper import map_category_name

                raw_category_name = enriched_data["category"]
                category_name = map_category_name(raw_category_name)

                category = db.query(Category).filter(Category.name == category_name).first()
                if not category:
                    logger.info(
                        f"Creating new canonical category from USDA (mapped from {raw_category_name}): {category_name}"
                    )
                    category = Category(name=category_name)
                    db.add(category)
                    db.commit()
                    db.refresh(category)
                category_id = category.id

            # 2. Find all similar items in the database to propagate this data
            all_items = db.query(Item).all()
            target_normalized = db_item.normalized_name

            # Identify items to update
            to_update = []
            for other in all_items:
                # Never clobber a manually pinned FDC match (the target item
                # itself is exempt: an explicit re-enrich clears the pin first)
                if other.fdc_override and other.id != db_item.id:
                    continue

                # Same normalized name is an automatic match
                if other.normalized_name == target_normalized:
                    to_update.append(other)
                    continue

                # High-confidence fuzzy match (85%+)
                score = fuzz.token_sort_ratio(target_normalized, other.normalized_name)
                if score >= 85:
                    to_update.append(other)

            # 3. Apply changes to all identified items
            updated_count = 0
            for item in to_update:
                # Update FDC metadata (auto match — clears any stale manual flag)
                item.fdc_id = enriched_data["fdc_id"]
                item.fdc_override = False
                item.gtin = enriched_data["gtin"]
                item.ingredients = enriched_data["ingredients"]

                # Fill nutrient data only where missing — never clobber existing
                # OFF/custom data (additive enrichment)
                if not item.nutrients and enriched_data.get("nutrients"):
                    item.nutrients = enriched_data["nutrients"]

                # Canonical Categorization: Always update if we have a category from FDC
                if category_id:
                    item.category_id = category_id

                updated_count += 1

            db.commit()
            logger.info(
                f"Enriched '{db_item.name}' and propagated FDC data to {updated_count} similar items."
            )
            return True
        except Exception as e:
            logger.error(f"Error saving FDC enrichment for item {item_id}: {e}")
            db.rollback()
            return False


fdc_service = FDCService()
