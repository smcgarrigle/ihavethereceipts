import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

# Define directories
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
env_path = BASE_DIR / ".env"

# Auto-configure secret key and database URL for local zero-config developer convenience
is_testing = os.getenv("TESTING") == "1"

# Load environment variables from the root .env file explicitly. Skipped under
# TESTING: .env carries the live DATABASE_URL and real API keys and would
# clobber the in-memory test database configured by conftest.py, sending test
# writes (and Gemini calls) to production data.
#
# override=False: variables already set in the caller's environment win over
# .env. Anyone exporting DATABASE_URL (seed scripts, the static-demo builder)
# is deliberately redirecting the app — .env only fills in what's unset.
if not is_testing:
    load_dotenv(dotenv_path=env_path, override=False)

if not is_testing:
    # Ensure SECRET_KEY exists
    if not os.getenv("SECRET_KEY"):
        try:
            generated_key = secrets.token_urlsafe(32)
            # If .env exists, append to it, otherwise create it
            with open(env_path, "a") as f:
                f.write(f"\nSECRET_KEY={generated_key}\n")
            # Pick up the just-appended value (unset vars load regardless of override)
            load_dotenv(dotenv_path=env_path, override=False)
        except Exception as e:
            raise RuntimeError(
                "SECRET_KEY environment variable is not set and auto-generation failed. "
                f"Application startup aborted: {e}"
            ) from e

    # Ensure DATABASE_URL exists. Always write an absolute path: a relative
    # sqlite URL resolves against the caller's CWD, so scripts run from the
    # wrong directory silently create empty stray databases.
    if not os.getenv("DATABASE_URL"):
        try:
            with open(env_path, "a") as f:
                f.write(f"\nDATABASE_URL=sqlite:///{BASE_DIR / 'grocery.db'}\n")
            load_dotenv(dotenv_path=env_path, override=False)
        except Exception as e:
            raise RuntimeError(
                "DATABASE_URL environment variable is not set and fallback setup failed. "
                f"Application startup aborted: {e}"
            ) from e

# Read verified values
secret_key_value = os.getenv("SECRET_KEY")
if not secret_key_value and not is_testing:
    raise RuntimeError("SECRET_KEY environment variable is not set. Application startup aborted.")

database_url_value = os.getenv("DATABASE_URL")
if not database_url_value and not is_testing:
    raise RuntimeError("DATABASE_URL environment variable is not set. Application startup aborted.")


class Settings:
    PROJECT_NAME: str = "IHaveTheReceipts"
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    DATA_DIR: Path = BASE_DIR.parent / "data"
    UPLOADS_DIR: Path = DATA_DIR / "uploads"

    # Security
    SECRET_KEY: str = secret_key_value or "test-secret-key-for-testing"

    # Database
    DATABASE_URL: str = database_url_value or "sqlite://"

    # OCR
    OCR_BACKEND: str = os.getenv("OCR_BACKEND", "local").lower()
    OCR_MODEL: str = os.getenv("OCR_MODEL", "llava:7b")
    OCR_BACKEND_URL: str = os.getenv("OCR_BACKEND_URL", "http://localhost:11434/v1")
    GEMINI_MODEL_NAME: str = os.getenv("GEMINI_MODEL_NAME", "gemini-flash")

    # Runtime state and caches. These live in one place because two of them
    # used to be CWD-relative (`Path("data/...")`), and both `make run` and
    # start_server.sh run from backend/ — so the daily usage counter, the OCR
    # cache and the model cache all resolved to a second `backend/data/`
    # directory, quietly splitting from the real one at the repository root.
    FEATURE_FLAGS_PATH: Path = DATA_DIR / "feature_flags.json"
    OCR_FILTERS_PATH: Path = DATA_DIR / "ocr_filters.json"
    OCR_USAGE_PATH: Path = DATA_DIR / "ocr_usage.json"
    OCR_CACHE_DIR: Path = DATA_DIR / "ocr_cache"
    KNOWN_MODELS_PATH: Path = DATA_DIR / "known_models.json"

    # There was a FEATURES dict and an is_enabled() classmethod here, reading
    # four ENABLE_* variables that .env.example documented as live. Nothing
    # anywhere called either of them, so setting ENABLE_BULK_AUTO_PROCESS=false
    # did nothing and said nothing. Deleted rather than wired up: none of the
    # four describes behaviour the app actually has a switch for.


settings = Settings()
