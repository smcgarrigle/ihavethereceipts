---
trigger: always_on
---

# IHaveTheReceipts - Agent Instructions

This document serves as the primary blueprint for all AI agents working on this project. It contains technology choices, coding style preferences, and architectural patterns established through development.

## Project Documentation
- [CHEATSHEET.md](/ihavethereceipts/CHEATSHEET.md): Quick reference guide for users.
- [DATA_DESIGN.md](/ihavethereceipts/DATA_DESIGN.md): Database schema, ERD, and field definitions.
- [EXCLUSIONS.md](/ihavethereceipts/EXCLUSIONS.md): Logic for junk filters and analytics exclusions.
- [PRD.md](/ihavethereceipts/PRD.md): Core instructions and product requirements.
- [ROADMAP.md](/ihavethereceipts/ROADMAP.md): Feature backlog, strategic vision, and completed milestones.
- [SBOM.md](/ihavethereceipts/SBOM.md): Software Bill of Materials — all dependencies and licenses.
- [README.md](/ihavethereceipts/README.md): GitHub instructions and project sharing guide.
- [SECURITY.md](/ihavethereceipts/SECURITY.md): Sensible security practices before pushing to GitHub or containerizing.
- [skill.md](/ihavethereceipts/skill.md): Portable AI operational blueprint and task guide.

## 1. Core Technology Stack
- **Backend**: Python 3.11, FastAPI
- **Database**: SQLite (Single-User, file-based, zero-config)
- **ORM**: SQLAlchemy with Alembic for migrations
- **Frontend**:
    - **Templates**: Jinja2
    - **Styles**: Tailwind CSS — **precompiled** to `static/css/tailwind.css` by `backend/scripts/build_css.sh` (standalone CLI v3.4.17, no Node). After adding/changing any Tailwind class in templates or `app/api/pages.py`, re-run the build script and commit the rebuilt CSS — new classes silently render unstyled otherwise. Dynamic class-name concatenation is invisible to the scanner; use literal class names.
    - **AJAX**: HTMX (Server-driven fragments)
    - **Reactivity**: Alpine.js (Lightweight client-side state)
- **AI/OCR**:
    - Primary: Google Gemini 3.x API family, prefer flash models
    - Local: Qwen2.5-VL or similar — via **LM Studio** or **Ollama**
    - **Finding Latest Models**: Use `app.services.model_manager.model_manager.fetch_available_models()` or check the `data/known_models.json` cache to see what models are available on your API key. The "Flash" models are typically the efficient/free tier choices.
    - **OCR Feedback Loop**: `app/services/correction_service.py` records human review corrections (`ocr_corrections` table) and builds the few-shot block injected into the receipt prompt by `process_receipt_task`. When changing the OCR prompt or models, measure the impact with `uv run python scripts/ocr_eval.py` (`--stored` = free baseline from past receipts, `--live` = re-run OCR). Note: the OCR result cache is keyed on image + full prompt text.

## 2. Coding Principles & Style
- **PEP 8 & Formatting**: Enforced automatically via **Ruff**. Run `uv run ruff check .` before committing.
- **Type Hinting**: Use Python type hints for all function signatures. Enforced via **Mypy** (`uv run mypy .`).
- **Pydantic**: Use Pydantic models for API request validation and response schemas.
- **UI/UX**:
    - **Multi-Theme Engine**: The frontend uses CSS variables for theming (`--bg-main`, `--bg-card`, `--text-base`, `--text-muted`, `--border-default`). All templates use semantic Tailwind classes (`bg-bgCard`, `text-textMuted`) — do NOT reintroduce hardcoded `bg-gray-800 dark:bg-gray-900` patterns. Theme variables are defined in `backend/static/css/themes.css`.
    - **Dark Mode First**: All UI components must look premium in dark mode.
    - **Mobile Responsive**: Use Tailwind's responsive prefixes (`sm:`, `md:`, `lg:`) to ensure usability on phones.
    - **HTMX over JS**: Prefer server-side rendered fragments and HTMX for dynamic content over complex frontend frameworks.
    - **Alpine.js for Client State**: Use Alpine.js for UI-only state (modals, tabs, local calculations).

## 3. Mandatory Workflow Rules
1. **Implementation Plans**: Always create an `implementation_plan.md` before making significant code changes.
2. **Quality Gates**: All commits must pass local **pre-commit hooks** (Ruff, Mypy). Run `uv run pre-commit install` once to set this up.
3. **Bug Fixes**: When a bug is reported, follow this sequence:
    - Create a test in `/tests` that reproduces the bug.
    - Fix the bug.
    - Prove the fix with the passing test.
4. **Receipt Processing**:
    - OCR data is stored in the `ocr_data` JSON field of the `Receipt` model.
    - Always maintain bi-directional price calculation (Total = Qty * UnitPrice).
    - Store names must be normalized using `app.services.store_utils.normalize_store_name`.
5. **AI Continuity**: Always check for recent **Knowledge Items (KIs)** at the start of a session. Review the latest handoff to understand the current "Save State" of the project before proposing new changes.

## 4. Hard-won Lessons (Anti-patterns to Avoid)
- **Alpine.js Inline Limitations**: Do **NOT** use `const` or `let` inside Alpine.js inline attributes (e.g., `@click`). It breaks in many environments. Move complex logic to the `x-data` object methods.
- **Jinja2 in JS**: When passing data from Jinja2 to JavaScript, use a hidden `<script type="application/json">` tag and parse it in JS. Avoid direct interpolation like `var data = {{ variable }}` which often breaks due to auto-formatting or escaping issues.
- **HTMX Return Types**: Ensure HTMX endpoints return HTML fragments, not JSON, unless the frontend is specifically designed to handle a JSON response. Returning raw JSON to an HTMX target will display the JSON string in the UI.
- **Database**: The project uses SQLite exclusively in development. The `DATABASE_URL` in `.env` should always point to `sqlite:///./grocery.db`.
- **Unit Price Math**: For bulk/weight tracking, always use `(Price * Qty) / TotalWeight`. Using `Price / (Weight * Qty)` leads to precision errors and $0.00 rounding issues in analytics.
- **Blocking the Event Loop**: Do **NOT** use `async def` for endpoints performing heavy synchronous I/O (Database, AI). This freezes the entire application. Use standard `def` instead; FastAPI runs these in a thread pool.
- **N+1 Database Queries**: Avoid querying within loops. Use SQLAlchemy `joinedload()` or batch fetch logic instead of fetching related items one-by-one in a list.
- **AI Rate Limiting**: Mass background migrations (100+ items) should use `gemini-2.0-flash` or `gemini-2.5-flash` with 2-5 second delays between chunks of 15-20 items to avoid `429 RESOURCE_EXHAUSTED` errors on free tier.
- **SQLite Concurrency**: When using SQLite, the **Bulk Loader** background service can cause "database is locked" errors if a user attempts to save a manual review at the same time. Enable WAL mode (`PRAGMA journal_mode=WAL`) to reduce locking contention for high-volume ingestion.
- **VS Code Markdown Links**: VS Code's internal markdown preview intercepts links to `http://localhost` and tries to resolve them as local workspace files, which breaks external browser routing. Always use `http://127.0.0.1` instead of `localhost` when generating markdown reports or documentation with local links.
- **Hardcoded Tailwind Theme Classes**: Do **NOT** add new `bg-white dark:bg-gray-800` or `text-gray-600 dark:text-gray-400` patterns. Use semantic variables: `bg-bgCard`, `text-textMuted`, `border-borderDefault`, etc. The mapping is in `themes.css`.


## 5. Directory Structure
- `backend/app/api/`: FastAPI route handlers (`analytics.py`, `analytics_fragments.py`, `pages.py`, `receipts.py`, `receipts_review.py`, `items.py`, `trends.py`, `xray.py`, `settings_router.py`, `predictions_router.py`, `search_router.py`, `export.py`, `bulk.py`).
- `backend/app/models/`: SQLAlchemy database models (`receipt.py`, `item.py`, `category.py`, `exclusion.py`, `ocr_correction.py`, `merge_log.py`, `store.py`).
- `backend/app/services/`: Business logic (`ocr.py`, `item_matcher.py`, `store_utils.py`, `pdf_parser.py`, `correction_service.py`, `predictions.py`, `fdc_service.py`, `external_product.py`, `nutrition_utils.py`, `category_mapper.py`, `category_cache.py`, `category_tagger.py`, `folder_watch.py`, `bulk_processor.py`, `receipt_service.py`, `model_manager.py`, `onboarding.py`).
- `backend/templates/`: HTML templates (layouts and pages).
- `backend/tests/`: Pytest test suite.

## 6. Logic Explanations (Data Enrichment)
- **Auto-merged (✨)**: Pure Python logic (using `rapidfuzz`) that matches OCR text to a "Master Item" record. It does NOT use the Gemini API.
- **History applied (📘)**: Local database lookup that inherits quantity/weight/units from the *most recent* purchase of the same item.
- **Live Augmentation**: These enrichments are applied "live" in `app.api.pages.review_receipt` every time the page is loaded.
