import json
import logging
import urllib.parse
import urllib.request
from typing import Any

from rapidfuzz import fuzz

logger = logging.getLogger(__name__)


class OpenFoodFactsService:
    BASE_URL = "https://world.openfoodfacts.org"
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    @staticmethod
    def _clean_query(query: str) -> str:
        """Strip OCR noise, store names, and measurements to improve search matching"""
        import re

        # 1. Lowercase and strip
        q = query.lower().strip()

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
        # Matches strings of 7+ digits
        q = re.sub(r"\b\d{7,}\b", "", q)

        # 5. Remove common measurements (e.g., "12 fl oz", "16oz", "32 ounce", "lb")
        q = re.sub(r"\b\d+\s*(fl\s*oz|oz|ounce|lb|g|kg|l|ml)\b", "", q)

        # 6. Expand common abbreviations (OCR-speak)
        abbreviation_map = {
            r"\bgrk\b": "greek",
            r"\bygrt\b": "yogurt",
            r"\byog\b": "yogurt",
            r"\bckn\b": "chicken",
            r"\bb/s\b": "boneless skinless",
            r"\bat[ \.]?na\b": "athena",
            r"\bvty\b": "variety",
            r"\bgrnd\b": "ground",
            r"\borg\b": "organic",
        }
        for abbr, full in abbreviation_map.items():
            q = re.sub(abbr, full, q)

        # 7. Final cleanup: remove extra punctuation and double spaces
        q = re.sub(r"[,|/]", " ", q)
        q = re.sub(r"\s+", " ", q).strip()

        return q

    @staticmethod
    def _fetch(url: str, retries: int = 5) -> dict[str, Any] | None:
        """Helper to perform GET request using urllib with simple retry"""
        import time

        for attempt in range(retries + 1):
            req = urllib.request.Request(
                url, headers={"User-Agent": OpenFoodFactsService.USER_AGENT}
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as response:
                    if response.status == 200:
                        return dict(json.loads(response.read().decode("utf-8")))
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed: {e}")
                if attempt < retries:
                    # Exponential backoff: 5s, 10s, 20s...
                    time.sleep(5 * (2**attempt))
                else:
                    logger.error(f"Error fetching from OFF after {retries} retries: {e}")

        return None

    @classmethod
    def search_product(cls, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Search products by name after cleaning the query"""
        cleaned_query = cls._clean_query(query)
        if not cleaned_query:
            return []

        logger.info(f"Searching OFF for cleaned query: '{cleaned_query}' (Original: '{query}')")

        params = urllib.parse.urlencode(
            {
                "search_terms": cleaned_query,
                "search_simple": 1,
                "action": "process",
                "json": 1,
                "page_size": limit,
            }
        )
        url = f"{cls.BASE_URL}/cgi/search.pl?{params}"

        data = cls._fetch(url)
        results = []

        if data and "products" in data:
            for p in data["products"]:
                results.append(cls._normalize_product(p))

        return results

    @classmethod
    def get_product_by_barcode(cls, barcode: str) -> dict[str, Any] | None:
        """Get single product by barcode"""
        url = f"{cls.BASE_URL}/api/v0/product/{barcode}.json"
        data = cls._fetch(url)

        if data and data.get("status") == 1:
            return cls._normalize_product(data["product"])
        return None

    @staticmethod
    def _normalize_product(p: dict[str, Any]) -> dict[str, Any]:
        """Extract only what we need"""
        # Extract nutrients
        nutriments = p.get("nutriments", {})
        nutrients = {
            "sodium_100g": nutriments.get("sodium_100g")
            or (float(nutriments.get("salt_100g", 0)) / 2.5 if nutriments.get("salt_100g") else 0),
            "fat_100g": nutriments.get("fat_100g", 0),
            "saturated_fat_100g": nutriments.get("saturated-fat_100g", 0),
            "saturated-fat_100g": nutriments.get("saturated-fat_100g", 0),
            "sugars_100g": nutriments.get("sugars_100g", 0),
            "proteins_100g": nutriments.get("proteins_100g", 0),
            # Keys consumed by nutrition_utils.calculate_receipt_item_macros —
            # previously omitted, causing OFF-enriched items to compute 0 kcal/carbs
            "energy-kcal_100g": nutriments.get("energy-kcal_100g", 0),
            "carbohydrates_100g": nutriments.get("carbohydrates_100g", 0),
            "fiber_100g": nutriments.get("fiber_100g", 0),
        }

        return {
            "code": p.get("code"),
            "product_name": p.get("product_name", "Unknown Product"),
            "brand": p.get("brands", ""),
            "image_url": p.get("image_front_url") or p.get("image_url"),
            "categories": p.get("categories", ""),
            "nutriscore": p.get("nutriscore_grade", "").upper(),
            "nutrients": nutrients,
        }

    @classmethod
    def enrich_db_item(cls, db, item_id: int) -> bool:
        """Enrich an item in the database using OFF data, and propagate to similar items."""
        from app.models.category import Category
        from app.models.item import Item

        db_item = db.query(Item).filter(Item.id == item_id).first()
        if not db_item:
            return False

        # 1. Try to match by GTIN if available
        enriched_data = None
        if db_item.gtin:
            logger.info(f"Attempting OFF lookup by GTIN: {db_item.gtin}")
            enriched_data = cls.get_product_by_barcode(db_item.gtin)

        # 2. Fallback to name search
        if not enriched_data:
            logger.info(f"Attempting OFF lookup by name: {db_item.name}")
            results = cls.search_product(db_item.name)
            if results:
                # Use fuzzy matching to find the best result
                scored_results: list[dict[str, Any]] = []
                for res in results:
                    full_name = f"{res['brand']} {res['product_name']}".strip()
                    score = fuzz.token_sort_ratio(db_item.name.lower(), full_name.lower())
                    scored_results.append({"score": score, "product": res})

                scored_results.sort(key=lambda x: float(str(x["score"])), reverse=True)
                if float(str(scored_results[0]["score"])) >= 80:
                    enriched_data = (
                        dict(scored_results[0]["product"])
                        if isinstance(scored_results[0]["product"], dict)
                        else None
                    )

        if not enriched_data:
            return False

        try:
            # 3. Establish Category
            category_id = None
            if enriched_data.get("categories"):
                # Take the first main category
                cat_list = [c.strip() for c in enriched_data["categories"].split(",")]
                if cat_list:
                    from app.services.category_mapper import map_category_name

                    # Canonical interceptor: OFF category names never create fragments
                    category_name = map_category_name(cat_list[0])
                    category = db.query(Category).filter(Category.name == category_name).first()
                    if not category:
                        category = Category(name=category_name)
                        db.add(category)
                        db.commit()
                        db.refresh(category)
                    category_id = category.id

            # 4. Propagate to similar items
            all_items = db.query(Item).all()
            target_normalized = db_item.normalized_name

            to_update = []
            for other in all_items:
                if other.normalized_name == target_normalized:
                    to_update.append(other)
                    continue
                score = fuzz.token_sort_ratio(target_normalized, other.normalized_name)
                if score >= 85:
                    to_update.append(other)

            # 5. Apply changes
            updated_count = 0
            for item in to_update:
                item.off_code = enriched_data["code"]
                if not item.gtin:
                    item.gtin = enriched_data["code"]
                item.image_url = enriched_data["image_url"]
                item.nutriscore = enriched_data["nutriscore"]
                item.nutrients = enriched_data["nutrients"]
                if category_id:
                    item.category_id = category_id
                updated_count += 1

            db.commit()
            logger.info(
                f"Enriched '{db_item.name}' with OFF data and propagated to {updated_count} items."
            )
            return True
        except Exception as e:
            logger.error(f"Error saving OFF enrichment for item {item_id}: {e}")
            db.rollback()
            return False
