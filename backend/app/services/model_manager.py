import asyncio
import datetime
import json
import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai

# Ensure env vars are loaded
load_dotenv()

logger = logging.getLogger(__name__)


class ModelManager:
    """
    Manages discovery, validation, and caching of Gemini models.
    Ensures the application always uses available models.
    """

    CACHE_FILE = Path("data/known_models.json")
    CACHE_DURATION_DAYS = 7

    # Preferred aliases/keywords in order of priority
    PREFERRED_KEYWORDS = ["flash", "pro", "latest", "exp"]

    def __init__(self):
        ocr_backend = os.getenv("OCR_BACKEND", "local").lower()
        self.api_key = os.getenv("GEMINI_API_KEY")

        if ocr_backend == "local":
            # Running in local LLaVA mode — Gemini client not needed
            logger.info("ModelManager: OCR_BACKEND=local, skipping Gemini init.")
            self.client = None
        elif not self.api_key:
            logger.warning("GEMINI_API_KEY not set. ModelManager will not work.")
            self.client = None
        else:
            self.client = genai.Client(api_key=self.api_key)

    def get_cached_models(self) -> dict[str, Any] | None:
        """Read models from disk if cache is valid."""
        if not self.CACHE_FILE.exists():
            return None

        try:
            data = dict(json.loads(self.CACHE_FILE.read_text()))
            last_updated = datetime.datetime.fromisoformat(data["last_updated"])

            # Check expiry
            if (datetime.datetime.now() - last_updated).days < self.CACHE_DURATION_DAYS:
                return data
            return None
        except Exception as e:
            logger.error(f"Failed to read model cache: {e}")
            return None

    def fetch_available_models(self) -> list[str]:
        """Query Google API for available models supporting generateContent."""
        if not self.client:
            return []

        valid_models = []
        try:
            logger.info("Fetching available Gemini models from API...")
            # Use the v1beta compatible list method
            # Based on list_models.py findings, client.models.list() returns items with .name
            for m in self.client.models.list():
                # Check for generateContent support
                # The explicit check might fail if attribute missing (as seen in debugging),
                # so we might need a safer check or rely on name convention if SDK is in flux.
                # However, the debug output showed 'supported_generation_methods' was missing on the object
                # returned by client.models.list() in the version installed.
                # Let's rely on name matching 'gemini' for now as a safe baseline,
                # or try-except the attribute access.

                model_name = m.name

                # Basic filtering
                if "gemini" not in model_name.lower():
                    continue

                # Store full resource name usually: models/gemini-1.5-flash
                # But SDK often takes just 'gemini-1.5-flash'.
                # Let's strip 'models/' prefix if present for cleaner usage.
                if model_name.startswith("models/"):
                    model_name = model_name.replace("models/", "")

                valid_models.append(model_name)

            return valid_models
        except Exception as e:
            logger.error(f"Error fetching models: {e}")
            return []

    def rank_models(self, models: list[str]) -> list[str]:
        """Sort models by preference."""

        def score_model(name):
            name = name.lower()
            score = 0

            # Penalties
            if "vision" in name:
                score -= 10  # Old 1.0 vision

            # Dynamic version scoring
            import re

            match = re.search(r"(\d+\.\d+)", name)
            if match:
                try:
                    version = float(match.group(1))
                    # Multiply version by 10 (e.g. 1.5 -> 15 points, 2.0 -> 20 points)
                    score += int(version * 10)
                except ValueError:
                    pass

            # Bonuses
            if "flash" in name:
                score += 5  # Ensures free-tier models bubble to top
            if "latest" in name:
                score += 2

            return score

        return sorted(models, key=score_model, reverse=True)

    def save_cache(self, models: list[str]):
        """Save discovered models to disk."""
        data = {
            "last_updated": datetime.datetime.now().isoformat(),
            "models": models,
            "best_model": models[0] if models else "gemini-flash",
        }

        # Ensure data dir exists
        self.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.CACHE_FILE.write_text(json.dumps(data, indent=2))
        logger.info(f"Saved {len(models)} models to cache.")

    async def ensure_models_updated(self):
        """Check cache and update if needed (async)."""
        cached = self.get_cached_models()
        if cached:
            logger.info(f"Model cache valid. Using {cached['best_model']}")
            return

        logger.info("Model cache missing or expired. Updating...")
        # Run synchronous API call in thread pool to avoid blocking async loop
        models = await asyncio.to_thread(self.fetch_available_models)

        if models:
            ranked = self.rank_models(models)
            self.save_cache(ranked)
        else:
            logger.warning("No models found via API. Keeping existing cache if any.")

    def get_best_model(self, fallback: str = "gemini-flash") -> str:
        """Get the best available model. Updates cache synchronously if missing."""
        if not self.CACHE_FILE.exists():
            logger.info("Cache missing in get_best_model. Fetching dynamically...")
            models = self.fetch_available_models()
            if models:
                ranked = self.rank_models(models)
                self.save_cache(ranked)
                return ranked[0]
            return fallback

        try:
            data = dict(json.loads(self.CACHE_FILE.read_text()))
            return str(data.get("best_model", fallback))
        except Exception:
            return fallback

    def get_fallback_models(self) -> list[str]:
        """Get list of fallback models from cache."""
        if not self.CACHE_FILE.exists():
            models = self.fetch_available_models()
            if models:
                ranked = self.rank_models(models)
                self.save_cache(ranked)
                return (
                    [m for m in ranked if m != ranked[0]][:5] if len(ranked) > 1 else ["gemini-pro"]
                )
            return ["gemini-pro", "gemini-flash"]

        try:
            data = json.loads(self.CACHE_FILE.read_text())
            models = data.get("models", [])
            best = data.get("best_model")

            # Return top 5 excluding the best one
            return [m for m in models if m != best][:5]
        except Exception:
            return ["gemini-pro"]


# Singleton instance
model_manager = ModelManager()
