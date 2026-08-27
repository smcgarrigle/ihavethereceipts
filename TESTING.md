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

### The `e2e` marker

`pytest.ini` sets `addopts = -m "not e2e"`, so **end-to-end tests are skipped by
default** — a normal run reports them as *deselected*, not failed. They drive a
real browser through Playwright and need a live server, which makes them slow and
dependent on a working browser install.

```bash
# Run only the end-to-end tests (needs a server on :8000 and Playwright browsers)
uv run pytest -m e2e

# Run everything, e2e included
uv run pytest -m ""
```

Currently marked `e2e`: `test_a11y_axe.py` and `test_dashboard_ui.py`.

## 📂 Test Coverage Breakdown

The tests live in `backend/tests/`. Grouped by what they protect:

| Area | Files | What they guard |
| :--- | :--- | :--- |
| **Fixtures** | `conftest.py` | In-memory SQLite plus a `get_db` override, so tests never touch the real database. |
| **Ingestion** | `test_duplicate_flow`, `test_manual_receipt`, `test_paste_receipt`, `test_ocr_merging`, `test_folder_watch`, `test_amazon_wf_mapping` | Upload, duplicate detection, manual and paste entry, OCR merge behaviour, the inbox watcher, and retailer-specific parsing. |
| **OCR backends** | `test_openrouter_backend`, `test_ocr_hint_banner` | Backend selection, and that the dashboard offers a hosted model rather than demanding one. |
| **Review & saving** | `test_receipt_review`, `test_save_reviewed_categories`, `test_zero_payload_guard`, `test_zero_qty_fix`, `test_correction_loop` | Review page robustness against bad `ocr_data`, category persistence, and the guards added after the $0-total incident. |
| **Items & matching** | `test_items`, `test_item_matcher`, `test_item_insights_bugs`, `test_size_extraction`, `test_unit_price_math`, `test_external_product` | Listing and grouping, fuzzy matching, size parsing, unit-price arithmetic, and OpenFoodFacts lookups (mocked — no real network calls). |
| **Nutrition & USDA** | `test_nutrition_phase1`, `test_nutrition_outliers`, `test_trends_nutrition`, `test_protein_roi_target`, `test_fdc_manual_override`, `test_seed_fdc_ids` | Coverage maths, outlier capping, ROI targets, and pinned FDC ids. |
| **Analytics** | `test_predictions`, `test_store_charts_data_driven`, `test_xray_exclusions`, `test_dashboard_integrity` | Restock cadence, per-store charts, X-Ray exclusions, and dashboard totals. |
| **Demo seed** | `test_seed_demo_totals` | Line items must reconstruct each receipt total — catches a line total being stored where a per-quantity price belongs. |
| **Accessibility** | `test_a11y_axe` *(e2e)*, `test_chart_a11y_labels`, `test_form_a11y_labels`, `test_img_alt_text`, `test_tablist_keyboard`, `test_category_store_stack_a11y` | axe-core smoke tests, chart and form labelling, alt text, and keyboard-reachable tabs. |
| **Template safety** | `test_template_integrity`, `test_fragment_html_escaping` | Critical DOM ids that JS/HTMX depend on, and escaping in rendered fragments. |
| **Cleanups** | `test_correctness_cleanup`, `test_medium_audit_cleanup` | Regression guards from past audit passes. |
| **Browser** | `test_dashboard_ui` *(e2e)* | Playwright click-through of modals and dynamic content. |

> Adding a test file? Add it to the right row above — the table is grouped, so it
> should not need a new row.

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

**Prevention**: Avoid saving files while a bulk job is actively processing. Consider running the server without `--reload` (`uvicorn app.main:app --host 127.0.0.1 --port 8000`) when doing bulk ingestion runs.
