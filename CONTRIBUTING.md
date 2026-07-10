# Contributing to Grocery Price Tracker

Thank you for your interest in contributing! This is a self-hosted, single-user grocery price tracking app built with Python, FastAPI, HTMX, and Google Gemini.

---

## Getting Started

### Prerequisites

- **Python 3.11+**
- **[uv](https://docs.astral.sh/uv/)** (package manager)
- A **Google Gemini API key** OR a local model server ([LM Studio](https://lmstudio.ai/) / [Ollama](https://ollama.com/))
- **System dependencies** (for PDF parsing):
  - Linux: `sudo apt install poppler-utils libmagic1`
  - macOS: `brew install poppler libmagic`

### Setup

```bash
git clone https://github.com/yourusername/grocery-tracker.git
cd grocery-tracker

# Copy and configure environment
cp .env.example .env
# Edit .env — add GEMINI_API_KEY or set USE_LOCAL_MODEL=true

# Install runtime + dev tools
cd backend
uv sync --extra dev
uv run pre-commit install
uv run uvicorn app.main:app --reload
```

Then open `http://127.0.0.1:8000`.

### Populate Demo Data (Optional)

To see the app fully populated before uploading your first receipt:

```bash
cd backend
uv run python scripts/seed_demo.py
```

---

## Project Structure

```
backend/
├── app/
│   ├── api/          # FastAPI route handlers
│   ├── models/       # SQLAlchemy models
│   ├── services/     # Business logic (OCR, matching, categorization)
│   └── main.py       # App entrypoint
├── alembic/          # Database migrations
├── scripts/          # Maintenance & utility scripts
├── static/           # CSS, JS, vendor libraries
├── templates/        # Jinja2 HTML templates
└── tests/            # Pytest test suite
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, SQLAlchemy, Alembic |
| Database | SQLite (file-based, zero-config) |
| Frontend | Jinja2, Tailwind CSS, HTMX, Alpine.js |
| AI / OCR | Google Gemini 3.5 Flash, IBM Granite 3.3 Vision (local), Qwen2-VL (local) |
| Testing | pytest |
| Linting | Ruff, Mypy |

---

## Development Workflow

### Quality Gates

All commits must pass the pre-commit hooks:

```bash
uv run ruff check .      # lint
uv run ruff format .     # format
uv run mypy .            # type check
uv run pytest            # test suite
```

Or use the Makefile shortcuts:

```bash
make lint    # ruff check + format
make test    # pytest
make run     # start dev server
```

### Dependency Management

Runtime and dev dependencies are separated in `pyproject.toml`. Users who only run the app install with `uv sync`; contributors install with `uv sync --extra dev`.

**Upgrading dependencies:**

```bash
cd backend

# Upgrade everything to latest compatible versions
uv lock --upgrade
uv sync --extra dev
uv run pytest && uv run ruff check . && uv run mypy .

# Or upgrade a single package
uv lock --upgrade-package fastapi
```

Commit the updated `uv.lock` after a passing test run.

**When to bump the `>=` floor in `pyproject.toml`:**
- Only when you actually depend on a feature from a newer version.
- Example: if you start using a FastAPI feature introduced in 0.115, change `fastapi>=0.104.1` to `fastapi>=0.115.0`.
- Otherwise, leave bounds loose to maximize compatibility for users.

### Database Migrations

When changing SQLAlchemy models, create an Alembic migration:

```bash
cd backend
uv run alembic revision --autogenerate -m "describe your change"
uv run alembic upgrade head
```

### Adding a New Feature

1. Add or modify a **SQLAlchemy model** in `backend/app/models/`
2. Create an Alembic migration
3. Add a **service** in `backend/app/services/` for business logic
4. Add a **route** in `backend/app/api/`
5. Create or update a **Jinja2 template** in `backend/templates/`
6. Write a **test** in `backend/tests/`

---

## Key Design Principles

- **HTMX over JavaScript**: Prefer server-side rendered fragments and HTMX for dynamic content.
- **Alpine.js for UI-only state**: Modals, tabs, dropdowns — anything that doesn't need the server.
- **Semantic Tailwind classes**: Use CSS variable-based tokens (`bg-bgCard`, `text-textMuted`) from `themes.css`. Do **not** add hardcoded `dark:bg-gray-800` patterns.
- **Dark mode first**: All UI should look premium in dark mode.
- **`def` not `async def` for DB endpoints**: FastAPI runs sync endpoints in a thread pool, which avoids blocking the event loop with SQLite I/O.

---

## Running Tests

```bash
cd backend
uv run pytest                     # all tests
uv run pytest tests/test_ocr_merging.py  # single file
uv run pytest -v                  # verbose output
```

---

## Bug Reports & Feature Requests

Please open a [GitHub Issue](../../issues) with:
- A clear description of the problem or request
- Steps to reproduce (for bugs)
- Your Python version and OS

---

## License

MIT — see [LICENSE](LICENSE) for details.
