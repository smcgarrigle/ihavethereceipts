import json
import logging
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)


class CategoryCache:
    """
    A persistent local JSON-based cache to store item-to-category mappings.
    This prevents redundant AI categorization calls before items are saved to the DB.
    """

    # Path is relative to the project root
    CACHE_FILE = Path(__file__).parent.parent.parent.parent / "data" / "category_cache.json"

    _instance = None
    _lock = Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._load()
            return cls._instance

    def _load(self):
        """Loads cache from disk."""
        self.data = {}
        if self.CACHE_FILE.exists():
            try:
                with open(self.CACHE_FILE) as f:
                    self.data = json.load(f)
                logger.info(f"✓ Loaded {len(self.data)} items from category cache.")
            except Exception as e:
                logger.error(f"Failed to load category cache: {e}")
        else:
            # Ensure data directory exists
            self.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            self._save()

    def _save(self):
        """Saves cache to disk."""
        try:
            with open(self.CACHE_FILE, "w") as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save category cache: {e}")

    def get(self, item_name: str) -> str | None:
        """Retrieves a category for a normalized item name."""
        normalized = item_name.strip().lower()
        return self.data.get(normalized)

    def set(self, item_name: str, category: str):
        """Stores a category for an item name."""
        normalized = item_name.strip().lower()
        if self.data.get(normalized) != category:
            with self._lock:
                self.data[normalized] = category
                self._save()

    def batch_get(self, item_names: list[str]) -> dict[str, str]:
        """Retrieves categories for a list of items. Returns only found items."""
        results = {}
        for name in item_names:
            cat = self.get(name)
            if cat:
                results[name] = cat
        return results

    def batch_set(self, mapping: dict[str, str]):
        """Bulk updates the cache."""
        if not mapping:
            return

        updated = False
        with self._lock:
            for name, cat in mapping.items():
                normalized = name.strip().lower()
                if self.data.get(normalized) != cat:
                    self.data[normalized] = cat
                    updated = True

            if updated:
                self._save()


# Singleton instance
category_cache = CategoryCache()
