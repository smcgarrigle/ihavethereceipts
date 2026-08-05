# IHaveTheReceipts Test Suite

This document describes the automated testing infrastructure for the The Receipts application. The generic test suite ensures backend stability, correct API behavior, and robust error handling.

## 🛠️ Testing Stack

-   **Framework**: `pytest`
-   **Client**: `FastAPI TestClient` (uses `httpx`)
-   **Database**: In-memory `SQLite` (isolated per session via `conftest.py`)
-   **Mocking**: `unittest.mock` (for OCR and External APIs)
-   **Linting & Formatting**: `ruff`
-   **Type Checking**: `mypy`

## 🛡️ Code Quality & Pre-commit
We use `pre-commit` to ensure code quality before it enters the repository.
1. Run `uv run pre-commit install` once to set up the git hooks.
2. The hooks will automatically run `ruff check .`, `ruff format .`, and `mypy .` on every commit.

To run these checks manually from the `backend/` directory:
```bash
uv run ruff check .
uv run mypy .
```

## 🚀 Running Tests

To run the full test suite, execute the following command from the `backend/` directory:

```bash
# Run all tests
uv run pytest

# Run a specific test file
uv run pytest tests/test_manual_receipt.py

# Run with output logs
uv run pytest -s
```

## 📂 Test Coverage Breakdown

The tests are located in `backend/tests/` and cover the following core features:

| Test File | Description | Key Scenarios |
| :--- | :--- | :--- |
| **`conftest.py`** | **Fixture Setup** | Configures the in-memory SQLite database and overrides the `get_db` FastAPI dependency to ensure tests run in isolation without affecting the real database. |
| **`test_duplicate_flow.py`** | **Duplicate Detection** | - Uploads a receipt twice.<br>- Mocks OCR response to ensure consistent data.<br>- Verifies the "Potential Duplicate" warning appears on the review page.<br>- Deletes the duplicate receipt. |
| **`test_manual_receipt.py`** | **Manual Entry** | - Creates a text-only manual receipt (Farmer's Market mode).<br>- Verifies default values (today's date, 0.00 total).<br>- **Critical**: Tests saving manual line items (verifying 422 validations and schema matching). |
| **`test_external_product.py`** | **External Data** | - Mocks `OpenFoodFacts` API response.<br>- Tests product search endpoint.<br>- Tests downloading and assigning product images (mocking `urllib` to prevent real network calls). |
| **`test_receipt_review.py`** | **Review UI** | - Verifies the Review Page loads correctly.<br>- Tests robustness against `NULL` dates or invalid JSON in `ocr_data`.<br>- Ensures the page doesn't crash (500 error) on malformed data. |
| **`test_items.py`** | **Item Management** | - Tests `GET /api/items/list`.<br>- Verifies items are correctly grouped by Category.<br>- Checks "Uncategorized" fallback logic. |
| **`test_template_integrity.py`** | **DOM Stability** | - Scans core pages (Dashboard, Receipts, Items, Review, Produce) for critical DOM IDs.<br>- Prevents runtime `TypeError` caused by missing elements required by JS/HTMX. |
| **`test_dashboard_ui.py`** | **UI Interaction** | - Uses Playwright to simulate browser clicks.<br>- Verifies that modals open and content updates correctly without JS errors. |

## 🧪 Key Testing Principles

1.  **Isolation**: Tests use a fresh in-memory database. Data created in one test does not persist to others.
2.  **Mocking External Services**:
    -   **OCR**: We mock `process_receipt_image` to avoid calling the expensive Gemini API during tests.
    -   **OpenFoodFacts**: We mock `urllib.request` to avoid hitting external APIs and ensure privacy/speed.
3.  **End-to-End Flows**: `test_duplicate_flow.py` simulates a complete user journey from Upload -> Review -> Delete.

## ⚠️ Known Operational Gotchas

### Bulk Processor: uvicorn `--reload` kills in-flight jobs
The `BulkProcessor` runs as a daemon thread inside the uvicorn process. When uvicorn reloads (triggered by any file change during development), the worker thread is killed immediately. Any receipt with `status = 'processing'` at that moment will be permanently stuck — the stuck-receipt timeout only resets items older than 1 hour.

**Symptoms**: Receipt shows "Ingesting..." indefinitely in the bulk queue UI; DB record has `status = 'processing'` with no `error_message`.

**Fix**: Manually reset the stuck receipt back to `pending`:
```bash
python -c "
from sqlalchemy import create_engine, text
import os; from dotenv import load_dotenv; load_dotenv()
engine = create_engine(os.getenv('DATABASE_URL'))
with engine.connect() as conn:
    conn.execute(text(\"UPDATE receipts SET status='pending', error_message=NULL WHERE id=<ID>\"))
    conn.commit()
"
```

**Prevention**: Avoid saving files while a bulk job is actively processing. Consider running the server without `--reload` (`uvicorn app.main:app --host 0.0.0.0 --port 8000`) when doing bulk ingestion runs.
