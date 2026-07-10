import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai.errors import ClientError
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

# Ensure env vars are loaded
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

logger = logging.getLogger(__name__)

# Configure Gemini
api_key = os.getenv("GEMINI_API_KEY")
client = None
if api_key:
    client = genai.Client(api_key=api_key)


def is_retryable(e):
    """Categorization calls are retryable on 429 and 500+ errors."""
    return isinstance(e, ClientError) and (e.code == 429 or e.code >= 500)


@retry(
    retry=retry_if_exception(is_retryable),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    stop=stop_after_attempt(2),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _generate_with_retry(model, contents):
    """Internal helper to call Gemini with tenacity retries."""
    return client.models.generate_content(model=model, contents=contents)


def categorize_item(item_name: str) -> str:
    """
    Use Gemini to categorize a grocery item with retry and fallback logic.
    """
    from app.services.category_cache import category_cache
    from app.services.model_manager import model_manager

    try:
        normalized = item_name.strip().lower()
        cached = category_cache.get(normalized)
        if cached:
            return cached

        if not client:
            return "Other"

        prompt = f"""
        You are a grocery store categorization system.

        Given this item name: "{item_name}"

        Return ONLY the category name from this list:
        - Produce (fruits, vegetables)
        - Dairy (milk, cheese, yogurt, eggs)
        - Meat (beef, chicken, pork, fish, seafood)
        - Bakery (bread, pastries, cakes)
        - Pantry (canned goods, pasta, rice, cereal, snacks, spices)
        - Beverages (water, juice, soda, coffee, tea, alcohol)
        - Frozen (frozen meals, ice cream)
        - Deli (lunch meat, prepared foods)
        - Health & Beauty (soap, shampoo, cosmetics)
        - Household (cleaning supplies, paper products)
        - Other (anything that doesn't fit)

        Return ONLY the category name, nothing else. No explanation.
        If unsure, return "Other".
        """

        # Primary and Fallback model search
        primary_model = os.getenv("GEMINI_MODEL_NAME") or model_manager.get_best_model(
            fallback="gemini-flash"
        )
        fallbacks = model_manager.get_fallback_models()
        models_to_try = list(
            dict.fromkeys([primary_model] + [m for m in fallbacks if m != primary_model])
        )

        response = None
        last_error = None

        for model in models_to_try:
            try:
                response = _generate_with_retry(model=model, contents=prompt)
                break
            except Exception as e:
                logger.warning(f"Categorization failed for model {model}: {e}")
                last_error = e

        if not response:
            logger.error(f"All models failed for categorization: {last_error}")
            return "Other"

        category = response.text.strip()

        # Save to cache
        category_cache.set(item_name, category)

        # Validate it's a known category
        valid_categories = [
            "Produce",
            "Dairy",
            "Meat",
            "Bakery",
            "Pantry",
            "Beverages",
            "Frozen",
            "Deli",
            "Health & Beauty",
            "Household",
            "Other",
        ]

        for valid_cat in valid_categories:
            if category.lower() == valid_cat.lower():
                return valid_cat

        return "Other"

    except Exception as e:
        logger.error(f"Critical Category tagging error: {e}")
        return "Other"


def categorize_items_batch(item_names: list) -> dict:
    """
    Categorize multiple items in one API call with retry and fallback.
    """
    from app.services.category_cache import category_cache
    from app.services.model_manager import model_manager

    try:
        if not client or not item_names:
            return {}

        # 1. Check Cache First
        results = {}
        to_categorize = []
        for name in item_names:
            cached = category_cache.get(name)
            if cached:
                results[name] = cached
            else:
                to_categorize.append(name)

        # 2. Return if everything was cached
        if not to_categorize:
            logger.info(f"✓ All {len(item_names)} items retrieved from category cache.")
            return results

        items_json = json.dumps(to_categorize)

        prompt = f"""
        You are a grocery store categorization system.

        Categorize each of these items into one of these categories:
        - Produce (fruits, vegetables)
        - Dairy (milk, cheese, yogurt, eggs)
        - Meat (beef, chicken, pork, fish, seafood)
        - Bakery (bread, pastries, cakes)
        - Pantry (canned goods, pasta, rice, cereal, snacks, spices)
        - Beverages (water, juice, soda, coffee, tea, alcohol)
        - Frozen (frozen meals, ice cream)
        - Deli (lunch meat, prepared foods)
        - Health & Beauty (soap, shampoo, cosmetics)
        - Household (cleaning supplies, paper products)
        - Other (anything that doesn't fit)

        Items to categorize:
        {items_json}

        Return ONLY a JSON object mapping each item to its category:
        {{
            "item name": "Category",
            "another item": "Category"
        }}

        No markdown, no explanation, just the JSON object.
        """

        primary_model = os.getenv("GEMINI_MODEL_NAME") or model_manager.get_best_model(
            fallback="gemini-flash"
        )
        fallbacks = model_manager.get_fallback_models()
        models_to_try = list(
            dict.fromkeys([primary_model] + [m for m in fallbacks if m != primary_model])
        )

        response = None
        last_error = None

        for model in models_to_try:
            try:
                response = _generate_with_retry(model=model, contents=prompt)
                break
            except Exception as e:
                logger.warning(f"Batch categorization failed for model {model}: {e}")
                last_error = e

        if not response:
            logger.error(f"All models failed for batch categorization: {last_error}")
            return {}

        content = response.text.strip()

        # Clean up markdown if present
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        result = json.loads(content)

        # Update Cache
        category_cache.batch_set(result)

        # Merge with cached results
        results.update(result)

        logger.info(
            f"✓ Categorized {len(result)} items using {model} ({len(item_names) - len(to_categorize)} from cache)"
        )
        return results

    except Exception as e:
        logger.error(f"Batch category tagging error: {e}")
        return {}
