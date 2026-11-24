import asyncio
import datetime
import json
import logging
import os
import re
from typing import Any

from dotenv import load_dotenv
from google import genai

from app.core.config import settings

# Skipped under TESTING so .env cannot override the test environment (see
# app/core/config.py). A bare load_dotenv() also searches parent directories,
# so from a git worktree it would load the main checkout's .env.
if os.getenv("TESTING") != "1":
    load_dotenv()

logger = logging.getLogger(__name__)

# General-purpose models, by name: gemini-<version>-flash|pro, optionally
# -lite and/or -preview, plus Google's moving -latest aliases. An allowlist
# rather than a denylist: Google keeps adding special-purpose suffixes (tts,
# live, image, transcribe, native-audio, customtools, computer-use...) and
# none of them can read a receipt, while the general names follow this shape.
_OCR_MODEL_RE = re.compile(
    r"^gemini-(?:\d+(?:\.\d+)?-(?:flash|pro)(?:-lite)?(?:-preview)?|(?:flash|flash-lite|pro)-latest)$"
)
_VERSION_RE = re.compile(r"^gemini-(\d+(?:\.\d+)?)-")


def is_ocr_model(name: str) -> bool:
    """True for a general Gemini model that can read a receipt image."""
    return bool(_OCR_MODEL_RE.match(name.lower()))


def pinned_gemini_model() -> str | None:
    """GEMINI_MODEL_NAME when it names a model; None for unset, empty or "auto".

    None means: use the best model from Google's live list (get_best_model).
    """
    value = (os.getenv("GEMINI_MODEL_NAME") or "").strip()
    return None if value.lower() in ("", "auto") else value


def _score_model(name: str) -> float:
    """Newest version first; flash (free tier) ahead of pro; stable ahead of preview."""
    name = name.lower()
    match = _VERSION_RE.match(name)
    score = float(match.group(1)) * 10 if match else 0.0
    if "flash" in name:
        score += 5
    if name.endswith("-latest"):
        score += 2
    if name.endswith("-preview"):
        score -= 1
    return score


class ModelManager:
    """
    Manages discovery, validation, and caching of Gemini models.
    Ensures the application always uses available models.
    """

    # Absolute via settings: this was CWD-relative, so the model cache split
    # between data/known_models.json and backend/data/known_models.json
    # depending on where the app was started. Both files exist on this machine.
    CACHE_FILE = settings.KNOWN_MODELS_PATH
    CACHE_DURATION_DAYS = 7

    # Preferred aliases/keywords in order of priority
    PREFERRED_KEYWORDS = ["flash", "pro", "latest", "exp"]

    def __init__(self):
        ocr_backend = os.getenv("OCR_BACKEND", "local").lower()
        self.api_key = os.getenv("GEMINI_API_KEY")

        if ocr_backend in ("local", "openrouter"):
            # Non-Gemini backend selected — Gemini client not needed
            logger.info(f"ModelManager: OCR_BACKEND={ocr_backend}, skipping Gemini init.")
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
        """Keep the models that can read a receipt, best first.

        Google's list mixes general models with speech, live-audio, image
        generation, embedding and other special-purpose ones (``-tts``,
        ``-live``, ``-image``, ``embedding``...). Ranking them all put
        ``gemini-3.8-flash-tts`` second, i.e. first in line as a fallback.
        """
        candidates = [m for m in models if is_ocr_model(m)]
        return sorted(candidates, key=_score_model, reverse=True)

    def _cached_ranking(self) -> list[str] | None:
        """The cached list, filtered and re-ranked; None when unreadable.

        Re-ranked on read rather than trusting the stored ``best_model``, so a
        cache written before the filter existed can't still pick a tts model.
        """
        try:
            data = dict(json.loads(self.CACHE_FILE.read_text()))
        except Exception:
            return None
        return self.rank_models(list(data.get("models", [])))

    def peek_best_model(self) -> str | None:
        """Best model from the cache, without calling Google; None if unknown."""
        if not self.CACHE_FILE.exists():
            return None
        ranked = self._cached_ranking()
        return ranked[0] if ranked else None

    def save_cache(self, models: list[str]):
        """Save discovered models to disk."""
        data = {
            "last_updated": datetime.datetime.now().isoformat(),
            "models": models,
            "best_model": models[0] if models else None,
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

    def get_best_model(self, fallback: str = "gemini-flash-latest") -> str:
        """Get the best available model. Updates cache synchronously if missing."""
        if not self.CACHE_FILE.exists():
            logger.info("Cache missing in get_best_model. Fetching dynamically...")
            models = self.fetch_available_models()
            if models:
                ranked = self.rank_models(models)
                self.save_cache(ranked)
                if ranked:
                    return ranked[0]
            return fallback

        cached = self._cached_ranking()
        return cached[0] if cached else fallback

    def get_fallback_models(self) -> list[str]:
        """Up to five models to try after the best one."""
        if not self.CACHE_FILE.exists():
            models = self.fetch_available_models()
            if models:
                ranked = self.rank_models(models)
                self.save_cache(ranked)
                return ranked[1:6]
            return ["gemini-flash-latest"]

        cached = self._cached_ranking()
        return cached[1:6] if cached else ["gemini-flash-latest"]


# Singleton instance
model_manager = ModelManager()
