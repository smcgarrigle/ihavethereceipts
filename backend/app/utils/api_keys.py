"""Reading API keys in a way that notices the .env.example placeholders.

Every guard in the app used to be `if not os.getenv("GEMINI_API_KEY")`. The
shipped `.env.example` carries `GEMINI_API_KEY=your_api_key_here`, which is
perfectly truthy, so a user who copied the example and filled in nothing got
past the guard and their first upload went to Google with a nonsense key.
"""

from __future__ import annotations

import os

# The literal values shipped in .env.example, plus the obvious neighbours.
PLACEHOLDERS = frozenset(
    {
        "your_api_key_here",
        "your_key_here",
        "your_fdc_key_here",
        "your-api-key",
        "your_api_key",
        "changeme",
        "change_me",
        "todo",
        "xxx",
        "none",
    }
)


def is_placeholder(value: str | None) -> bool:
    """Whether a key is absent, blank, or one of the example stand-ins."""
    if value is None:
        return True
    normalised = value.strip().strip("\"'").lower()
    if not normalised:
        return True
    if normalised in PLACEHOLDERS:
        return True
    # your_openrouter_key_here, your-gemini-key-here, and so on.
    return normalised.startswith("your") and normalised.endswith("here")


def configured_key(name: str) -> str | None:
    """The environment variable's value, or None if it is not a real key."""
    value = os.getenv(name)
    return None if is_placeholder(value) else value
