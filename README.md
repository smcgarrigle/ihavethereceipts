# 🛒 Grocery Price Tracker

A self-hosted, AI-powered receipt tracker that builds a personal price history database from your grocery receipts. Built with **FastAPI**, **SQLite**, **HTMX**, and **Google Gemini 3.5**.

## 🚀 Key Features

### 📄 Intelligent Receipt Processing
- **AI OCR**: Takes images (JPG/PNG) or PDFs and extracts data using **Google Gemini 3.5** or local models like **IBM Granite 3.3 Vision** or **Qwen2-VL** via **LM Studio** or **Ollama**.
- **Local Model Support**: Run OCR entirely on your own hardware for privacy and zero API costs.
- **Smart Parsing**: Handles discounts, varied unit types (oz, lb, etc.), and complex "2 for $X" deals.
- **Interactive Review (Human-in-the-Loop)**: Verify and edit OCR results before saving. The AI extracts data into a safe sandbox, and your analytics charts remain completely untouched until you explicitly click "Save". *It's your data, you approve it.*
- **Self-Improving OCR (Feedback Loop)**: Every correction you make in the review sandbox is remembered. Renames, price fixes, and missed items are stored per store and injected into future OCR prompts as few-shot examples — the extractor literally learns your stores' receipt dialects over time.
- **Structured Outputs + Eval Harness**: The Gemini path uses a response schema for guaranteed-valid JSON, and `scripts/ocr_eval.py` measures extraction accuracy against your own reviewed receipts (`--stored` for a free baseline, `--live` to benchmark prompt or model changes).
- **Reprocessing Tool**: CLI script to re-run OCR on historical receipts to test different models.

> [!NOTE]
> **Edge Cases & Why Things Don't Always Add Up**
> Every store's Point-of-Sale (POS) system is like its own dialect. Some stores (like Target) distribute a basket discount (e.g., "$5 off $50") proportionally across every single item. Others just dump a massive "-$5.00" string at the very bottom of the receipt, leaving the AI completely guessing what it applies to (often attaching it to the last scanned item!). The "Sandbox Review" step exists specifically to smooth out these store-specific idiosyncrasies, allowing you to separate out basket-level rewards into negative line items or manually adjust prices to perfectly balance the math before the data pollutes your spending analytics.

### 📊 Powerful Analytics
- **Dashboard**: At-a-glance view of monthly spending, top categories, and recent trips.
- **Trends Page**: Visualize price history for any item with interactive scatter plots.
- **Store Comparison**: See which store offers the best price for your favorite items.
- **Spending History**: Searchable, filterable history of every dollar spent.

### 🧠 Advanced Item Management
- **Duplicate Detection**: Fuzzy matching identifies duplicate items across different receipts (e.g., "Bananas" vs "Banana Organic").
- **Smart Merging**: Merge duplicates to keep your price history clean while preserving original receipt data.
- **Auto-Categorization**: AI automatically tags items into categories (Produce, Dairy, Snacks, etc.).
- **Dismissal Memory**: "Dismiss" incorrect duplicate suggestions, and the system remembers to ignore them in the future.

### 📱 Mobile-First Design
- **Responsive UI**: Fully optimized for phones with a collapsible hamburger menu and touch-friendly controls.
- **Dark Mode**: Sleek, battery-saving dark interface.
- **Drawers**: Complex data on the Items page is tucked away in collapsible drawers for a clean mobile experience.

## 🛠️ Technology Stack

### 🏗️ Frameworks & Backend
- **FastAPI**: Modern, high-performance web framework for Python 3.11+.
- **SQLAlchemy**: Robust SQL toolkit and Object Relational Mapper for database operations (synchronous sessions; endpoints run in FastAPI's threadpool).
- **Alembic**: Lightweight database migration tool for SQLAlchemy.
- **Jinja2**: Flexible Python templating engine for server-driven HTML fragments.
- **Pydantic v2**: State-of-the-art data validation and schema management.

### 🛠️ Developer Tools & Quality
- **Ruff**: Lightning-fast Python linter and code formatter.
- **Mypy**: Static type checking for strict schema enforcement.
- **Pre-commit**: Automated git hooks to ensure code quality on every commit.
- **pytest**: Comprehensive unit and integration testing framework.

### 🎨 Frontend & Styling
- **Tailwind CSS**: Utility-first CSS for premium, dark-mode-first design.
- **HTMX**: Enables seamless, server-driven interactivity without heavy JS frameworks.
- **Alpine.js**: Lightweight reactivity for client-side logic (modals, drawers, and tabs).
- **Chart.js**: Interactive data visualization for price trends and spending analytics.

### 📊 Data & AI Tools
- **Google GenAI (Gemini 3.5)**: Primary engine for high-accuracy OCR and categorization.
- **LM Studio / Ollama**: Integration support for local, privacy-preserving vision models (IBM Granite 3.3 Vision, Qwen2-VL).
- **RapidFuzz / FuzzyWuzzy**: High-performance string matching for item deduplication.
- **pdfplumber / pdf2image**: Specialized libraries for extracting structured data from digital and scanned PDFs.
- **json-repair**: Automated correction of malformed JSON from AI outputs.

### 🗄️ Database
- **SQLite**: Primary database for portability and single-user simplicity.

> [!NOTE]
> **Bulk Loader Concurrency**: The Bulk Loader uses a background queue. SQLite WAL mode is enabled by default to minimize locking. For extremely high-volume batch imports, consider adding a brief delay between chunks.


## 🤖 AI Development (Ensemble Programming)

This project has been developed through **Ensemble AI Programming**, leveraging a coordinated group of AI agents and models to architect, implement, and maintain the codebase:

- **AI Agent**: [Antigravity](https://github.com/google-deepmind/antigravity) (Google DeepMind)
- **Primary Models**: Built with **Gemini 3 Flash** and **Gemini 3.5**.
- **OCR Logic**: Orchestrated via **Gemini 3.5 Flash** and locally verified with **IBM Granite 3.3 Vision**.

In this ensemble approach, different models specialize in specific tasks—from high-level architectural planning to precise code execution and OCR data parsing—ensuring a robust and scalable application.

## ⚡ Quick Start

### Prerequisites
- Python 3.11+
- Google Gemini API Key **OR** a local model server ([LM Studio](https://lmstudio.ai/) or [Ollama](https://ollama.com/))

### Setup

1.  **Clone & Configure**:
    ```bash
    git clone https://github.com/yourusername/grocery-tracker.git
    cd grocery-tracker
    cp .env.example .env
    # Edit .env with your GEMINI_API_KEY OR local model settings
    # USE_LOCAL_MODEL=true
    # LOCAL_MODEL_NAME=ibm/granite3.3-vision:2b
    ```

2.  **Install & Run (Local SQLite)**:
    ```bash
    cd backend
    uv sync                          # installs runtime dependencies only
    uv run uvicorn app.main:app --reload
    ```

    > [!TIP]
    > **Contributing?** Install dev tools (linter, type checker, tests) with:
    > ```bash
    > uv sync --extra dev
    > uv run pre-commit install
    > ```

3.  **Optional: Local AI models (LM Studio or Ollama)**:
    For privacy-preserving, offline OCR using Granite or Qwen:
    ```bash
    # LM Studio: download from https://lmstudio.ai and load a Qwen2-VL or Granite model
    # Ollama:
    ollama pull granite3.3-vision:2b   # or qwen2-vl
    ```

4.  **Access App**: Open `http://127.0.0.1:8000`


## 🧪 Quick Demo (No Receipts Needed)

Want to see the app with real-looking data before scanning your first receipt? Run the demo seed script:

```bash
cd backend
uv run python scripts/seed_demo.py
```

This populates the database with ~25 fictional receipts across 5 stores (Trader Joe's, Costco, Amazon Fresh, Whole Foods, Safeway) spanning 4 months — enough to make every dashboard chart and trends page come alive.


## 📦 Dependency Management

Dependencies are declared in `backend/pyproject.toml` and pinned in `backend/uv.lock`.

| Audience | Install command | What you get |
|---|---|---|
| **Users** | `uv sync` | Runtime deps only (FastAPI, SQLAlchemy, Gemini, etc.) |
| **Contributors** | `uv sync --extra dev` | Runtime + dev tools (Ruff, Mypy, pytest, pre-commit) |

### Frontend assets are NOT covered by uv

`uv.lock` pins Python packages only. The frontend stack is vendored and updated manually:

| Asset | Where | How to update |
|---|---|---|
| Tailwind CSS | `static/css/tailwind.css` (compiled) | Bump `VERSION` in `scripts/build_css.sh`, delete `tools/tailwindcss`, re-run the script, then visually check key pages. **Major versions (v4+) change the config format — do not bump casually.** |
| HTMX / Alpine.js / Chart.js | `static/js/vendor/` | Download the new minified build over the old file, update [SBOM.md](SBOM.md), and exercise the UI (modals, drawers, charts). |
| Inter font | `static/fonts/` | Re-vendor the woff2 subsets and regenerate `inter.css`. |

**Tailwind precautions (precompiled build):**

1. `static/css/tailwind.css` only contains classes that existed in the templates when it was last built. **After adding any new Tailwind class, re-run `./scripts/build_css.sh`** and commit the rebuilt CSS together with the template change — otherwise the class silently renders unstyled.
2. The content scan covers `templates/**/*.html`, `app/api/pages.py`, and `static/js/**/*.js` (see `tailwind.config.js`). If you embed HTML with Tailwind classes anywhere else, add that path to `content` or the classes won't compile.
3. Dynamically constructed class names (string concatenation in Jinja/Alpine/JS) are invisible to the scanner — always write full literal class names, or add them to a `safelist` in `tailwind.config.js`.
4. Do not swap Alpine.js for its CSP build or remove `'unsafe-eval'` from the CSP: the standard Alpine build evaluates inline expressions via the `AsyncFunction` constructor, and every modal/drawer/tab depends on it.

### Keeping Python dependencies up to date

- **Practice:** the committed `uv.lock` keeps installs reproducible indefinitely — nothing breaks if you never update. Refresh it deliberately (every few months, or after a CVE) rather than routinely, and always run the tests before committing the new lock.

```bash
cd backend

# Upgrade everything to latest compatible versions
uv lock --upgrade
uv sync --extra dev
uv run pytest && uv run ruff check . && uv run mypy .   # verify

# Or upgrade a single package
uv lock --upgrade-package fastapi
```

Commit the updated `uv.lock` after a successful test run. Only raise the `>=` floor in `pyproject.toml` when you depend on a feature from a newer version.

> [!NOTE]
> For security auditing, run `uv run pip-audit` periodically. See [SBOM.md](SBOM.md) for the full dependency inventory.


## 🔮 Roadmap

See [ROADMAP.md](ROADMAP.md) for the full strategic backlog. Highlights:

- [ ] **Interactive Chart Filters**: Dropdown menus to filter charts by date, store, or category.
- [ ] **Barcode Scanning**: Mobile camera integration via OpenFoodFacts.
- [ ] **Volatility Alerts**: Notify when an item's price shifts >15% in 30 days.
- [x] **Local Folder Watch**: Auto-ingest PDFs dropped into `data/inbox` (disable with `FOLDER_WATCH=0`).
- [ ] **PWA / Offline Mode**: Scan receipts in-store without connectivity.


## 🍎 Running on Mac M1 / M2 (Apple Silicon)

The app runs natively on Apple Silicon. Follow these steps after cloning the repo.

### 1. Install System Dependencies

```bash
# Homebrew (if not installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# uv (Python package manager)
brew install uv

# Required system libraries
brew install poppler    # for pdfplumber / pdf2image
brew install libmagic   # for python-magic file type detection

# Optional: Local AI models via LM Studio or Ollama
# LM Studio: download from https://lmstudio.ai — load a Qwen2-VL or Granite vision model
# Ollama alternative:
brew install ollama
ollama pull granite3.3-vision:2b   # or qwen2-vl
```

### 2. Clone & Configure

```bash
git clone https://github.com/yourusername/grocery-tracker.git
cd grocery-tracker
cp .env.example .env
# Edit .env — add your GEMINI_API_KEY or set USE_LOCAL_MODEL=true
```

### 3. Install & Run

```bash
cd backend
uv sync                          # creates .venv and installs runtime deps
uv run uvicorn app.main:app --reload

# Contributing? Also install dev tools:
uv sync --extra dev
uv run pre-commit install
```

Then open `http://127.0.0.1:8000`.

### 4. Shortcut: Use the Makefile

A `Makefile` in the project root wraps the common commands:

```bash
make setup   # uv sync + pre-commit install
make run     # start the dev server
make test    # run pytest suite
make lint    # ruff check + format
```

### Mac M1 Notes

| Issue | Resolution |
|---|---|
| `pdfplumber` fails to open PDFs | Run `brew install poppler` |
| `python-magic` import error | Run `brew install libmagic` |
| Port 8000 already in use | Change with `--port 8001` in `make run` |
| LM Studio / Ollama models slow on first run | First inference downloads model weights — normal |
| SQLite `database is locked` | WAL mode is enabled by default; this is rare under normal use |

> [!TIP]
> The app defaults to **SQLite** (zero config). No extra database setup needed for single-user use on Mac.
