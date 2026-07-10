# Grocery Tracker - AI Skill Blueprint

This document defines the operational "skills" and knowledge required for an AI agent to effectively manage, maintain, and evolve the Grocery Tracker project.

## 1. Project DNA
- **Goal**: Track grocery prices, nutritional data, and spending trends using OCR and USDA FDC integration.
- **Backend**: FastAPI (Python 3.11+)
- **Frontend**: Jinja2 + Tailwind CSS + HTMX + Alpine.js
- **Database**: SQLite (file-based, zero-config)
- **AI**: Google Gemini for OCR/Matching, USDA FDC for Nutrition.
- **Local AI**: LM Studio (preferred) or Ollama for self-hosted vision models.

## 2. Environment Management (Portable)
Always use `uv` for environment management to ensure consistency across Linux, macOS, and Windows.

- **Setup (users)**: `cd backend && uv sync`
- **Setup (contributors)**: `cd backend && uv sync --extra dev && uv run pre-commit install`
- **Upgrade deps**: `cd backend && uv lock --upgrade && uv sync --extra dev`

## 3. Core Operational Skills

### Running the Application
| Task | Command (Linux/macOS) | Command (Windows) |
| :--- | :--- | :--- |
| **Start Server** | `cd backend && ./start_server.sh` | `cd backend && python -m uvicorn app.main:app --reload` |
| **Run Migrations** | `cd backend && alembic upgrade head` | `cd backend && alembic upgrade head` |
| **Database Shell** | `sqlite3 grocery.db` | `sqlite3 grocery.db` |

### Receipt Processing Flow
1. **OCR Ingestion**: Receipts are uploaded via `/api/receipts/upload`.
2. **Review Logic**: Logic resides in `backend/app/main.py` under `review_receipt`.
3. **Price Normalization**: Always use `app.services.store_utils.normalize_store_name`.
4. **Calculations**: `UnitPrice = (Price * Qty) / TotalWeight` for bulk items.

### USDA FDC Enrichment
- **Single Item**: Triggered via the "Insights" or "USDA Match" button in the UI.
- **Batch Backfill**: Use `backend/scripts/backfill_ingredients.py`.
- **Service**: `backend/app/services/fdc_service.py` handles all API communication.

## 4. UI/UX Standards (Mandatory)
- **Dark Mode First**: Use semantic CSS variable tokens (`bg-bgCard`, `text-textBase`, `border-borderDefault`). Do **NOT** use hardcoded classes like `bg-gray-900` or `dark:bg-gray-800`.
- **Responsive**: Always test with mobile-first Tailwind prefixes (`sm:`, `md:`, `lg:`).
- **Interactivity**: 
    - Use **HTMX** for server-driven partial updates (`hx-get`, `hx-post`).
    - Use **Alpine.js** for client-side state (modals, toggles).
    - **NO** complex React/Vue components unless explicitly requested.

## 5. Cross-Platform Portability Rules
- **Path Handling**: Use `os.path.join` or `Pathlib` in Python. In documentation, use forward slashes `/` as they are generally supported by Git Bash and WSL on Windows.
- **Environment Variables**: Store sensitive keys (GEMINI_API_KEY, FDC_API_KEY) in a `.env` file in the `backend/` directory. Use `python-dotenv` to load them.
- **Line Endings**: Ensure `.gitattributes` is set to handle LF/CRLF transitions automatically.

## 6. Testing & Quality Control
- **Run Tests**: `cd backend && uv run pytest`
- **Linting**: `cd backend && uv run ruff check .`
- **Format**: `cd backend && uv run ruff format .`
- **Type Checking**: `cd backend && uv run mypy .`
- **Pre-commit**: `cd backend && uv run pre-commit install` (Run once locally to enable automated checks on commit).

## 7. Troubleshooting
- **DB Locked**: SQLite "database is locked" errors occur during concurrent writes (e.g., bulk import + manual review). WAL mode is enabled by default to reduce this.
- **429 Errors**: USDA and Gemini APIs have rate limits. Implement `time.sleep()` in loop-based enrichment scripts.

## 8. Agent Communication Mode: Caveman

The following is an active persona definition for the AI agent to reduce token usage during long sessions.

---
name: caveman
description: >
  Ultra-compressed communication mode. Cuts token usage ~75% by dropping
  filler, articles, and pleasantries while keeping full technical accuracy.
  Use when user says "caveman mode", "talk like caveman", "use caveman",
  "less tokens", "be brief", or invokes /caveman.
---

Respond terse like smart caveman. All technical substance stay. Only fluff die.

### Persistence

ACTIVE EVERY RESPONSE once triggered. No revert after many turns. No filler drift. Still active if unsure. Off only when user says "stop caveman" or "normal mode".

### Rules

Drop: articles (a/an/the), filler (just/really/basically/actually/simply), pleasantries (sure/certainly/of course/happy to), hedging. Fragments OK. Short synonyms (big not extensive, fix not "implement a solution for"). Abbreviate common terms (DB/auth/config/req/res/fn/impl). Strip conjunctions. Use arrows for causality (X -> Y). One word when one word enough.

Technical terms stay exact. Code blocks unchanged. Errors quoted exact.

Pattern: `[thing] [action] [reason]. [next step].`

Not: "Sure! I'd be happy to help you with that. The issue you're experiencing is likely caused by..."
Yes: "Bug in auth middleware. Token expiry check use `<` not `<=`. Fix:"

### Examples

**"Why React component re-render?"**

> Inline obj prop -> new ref -> re-render. `useMemo`.

**"Explain database connection pooling."**

> Pool = reuse DB conn. Skip handshake -> fast under load.

### Auto-Clarity Exception

Drop caveman temporarily for: security warnings, irreversible action confirmations, multi-step sequences where fragment order risks misread, user asks to clarify or repeats question. Resume caveman after clear part done.

Example -- destructive op:

> **Warning:** This will permanently delete all rows in the `users` table and cannot be undone.
>
> ```sql
> DROP TABLE users;
> ```
>
> Caveman resume. Verify backup exist first.
