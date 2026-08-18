# 🧾 IHaveTheReceipts

A self-hosted, AI-powered receipt tracker that builds a personal price history database from your grocery receipts. Built with **FastAPI**, **SQLite**, **HTMX**, and **Google Gemini**.

## 🚀 Key Features

### 📄 Intelligent Receipt Processing
- **AI OCR**: Takes images (JPG/PNG) or PDFs and extracts data using **Google Gemini 3.x** (Flash or Pro) or local models like **Qwen2.5-VL** via **LM Studio** or **Ollama**.
- **Paste-Text Ingestion**: Got a digital receipt or order-confirmation email? Just copy-paste the text — no screenshot or PDF needed.
- **Local Model Support**: Run OCR entirely on your own hardware for privacy and zero API costs.
- **Smart Parsing**: Handles discounts, varied unit types (oz, lb, etc.), and complex "2 for $X" deals.
- **Interactive Review (Human-in-the-Loop)**: Verify, edit, and approve OCR results before saving. Your analytics remain untouched until you explicitly click "Save". *It's your data, you approve it.*
- **Self-Improving OCR (Feedback Loop)**: Every correction you make is remembered. Renames, price edits, and missed items are stored per-store and injected into future OCR prompts as few-shot examples — the extractor literally learns your stores' receipt dialects over time.
- **Structured Outputs + Eval Harness**: The Gemini path uses a response schema for guaranteed-valid JSON. `scripts/ocr_eval.py` measures extraction accuracy against your own reviewed receipts (`--stored` for a free baseline, `--live` to benchmark prompt or model changes).
- **Reprocessing Tool**: CLI script to re-run OCR on historical receipts to test different models.
- **Auto-Ingest**: Drop PDFs/images into `data/inbox` and they process automatically through the full OCR + review pipeline. (`FOLDER_WATCH=0` to disable.)

> [!NOTE]
> **Edge Cases & Why Things Don't Always Add Up**
> Every store's POS system has its own dialect. Some stores (like Target) distribute a basket discount proportionally across every item. Others put a "-$5.00" line at the bottom, leaving the AI to guess what it applies to. The **Sandbox Review** step exists to smooth out these idiosyncrasies — separate basket-level rewards into negative line items, or manually adjust prices before data hits your analytics. These corrections are remembered and improve future OCR.

### 📊 Powerful Analytics
- **Dashboard**: At-a-glance view of monthly spending, top categories, and recent trips.
- **Trends Page**: Visualize price history for any item with interactive charts.
- **Store Comparison**: See which store offers the best price for your favorite items.
- **Spending History**: Searchable, filterable history of every dollar spent.

### 🧠 Advanced Item Management
- **Duplicate Detection**: Fuzzy matching identifies duplicate items across receipts (e.g., "Bananas" vs "Banana Organic").
- **Smart Merging**: Merge duplicates to keep price history clean while preserving original receipt data.
- **Auto-Categorization**: AI automatically tags items into a strict 13-category canonical taxonomy.
- **Dismissal Memory**: "Dismiss" incorrect duplicate suggestions, and the system remembers them.

### 🥦 Nutrition Insights
- **Automatic Enrichment**: Items are matched against the **USDA FoodData Central** database for nutrition facts, brands, and categories.
- **User-Entered Nutrition Data**: When databases don't know a product, enter or correct nutrition facts from the item's insights page — your values take precedence everywhere.
- **Honest Coverage**: The trends page shows exactly what share of your spending has nutrition data, so charts never silently overstate coverage.
- **Extensible Sources**: The enrichment layer is pluggable — an [OpenFoodFacts](https://world.openfoodfacts.org/) integration is scaffolded.

### 🔐 Your Data, In and Out
- **Export Everything**: Download any receipt or your entire purchase history as **CSV or Excel** at any time.
- **Delete Anything**: Remove individual items, whole receipts, or wipe **all** data from the Settings page. Self-hosted means easy exit, not just easy entry.

### 📱 Mobile-First Design
- **Responsive UI**: Fully optimized for phones with a collapsible hamburger menu and touch-friendly controls.
- **Multi-Theme Engine**: Light, Dark, Forest, and Sunset themes — all CSS-variable based, dark mode first.
- **Drawers**: Complex data on the Items page is tucked into collapsible drawers for a clean mobile experience.

## 🛠️ Technology Stack

### 🏗️ Frameworks & Backend
- **FastAPI**: Modern, high-performance web framework for Python 3.11+.
- **SQLAlchemy**: SQL toolkit and ORM (synchronous sessions; endpoints run in FastAPI's threadpool).
- **Alembic**: Database migration tool — the single schema authority, runs at startup.
- **Jinja2**: Python templating engine for server-driven HTML fragments.
- **Pydantic v2**: Data validation and schema management.

### 🛠️ Developer Tools & Quality
- **Ruff**: Python linter and code formatter.
- **Mypy**: Static type checking.
- **Pre-commit**: Automated git hooks to enforce code quality on every commit.
- **pytest**: Unit and integration testing framework.

### 🎨 Frontend & Styling
- **Tailwind CSS**: Utility-first CSS (precompiled to `static/css/tailwind.css` — no Node required).
- **HTMX**: Server-driven interactivity without heavy JS frameworks.
- **Alpine.js**: Lightweight reactivity for client-side logic (modals, drawers, tabs).
- **Chart.js**: Interactive data visualization for price trends and spending analytics.

### 📊 Data & AI Tools
- **Google GenAI (Gemini 3.x)**: Primary engine for high-accuracy OCR and categorization (Flash models recommended for free-tier use).
- **LM Studio / Ollama**: Local, privacy-preserving vision models (IBM Granite 3.3 Vision, Qwen2-VL).
- **RapidFuzz**: High-performance string matching for item deduplication.
- **pdfplumber / pdf2image**: Structured data extraction from digital and scanned PDFs.
- **json-repair**: Automated correction of malformed JSON from AI outputs.

### 🗄️ Database
- **SQLite**: Primary database for portability and single-user simplicity. WAL mode is enabled by default to minimize locking under the background bulk loader.


## 🤖 AI Development (Ensemble Programming)

This project is developed through **Ensemble AI Programming** — a coordinated group of AI harnesses and models, each with a distinct role:

- **Primary Harness**: [Antigravity](https://antigravity.google) (Google) drives the main implementation work, with **Gemini Flash** and **Gemini 3.5** as the primary coding models.
- **Review & Improvement**: **Anthropic Claude** (Opus, Sonnet, and Fable via Claude Code/Claude CLI) runs code review, refactoring, and hardening passes.
- **Independent Sanity Reviews**: Periodic whole-project reviews with **Z.ai (GLM)** and other models — a deliberately different model family to catch blind spots the primary models might share.
- **Runtime OCR**: **Gemini Flash** (cloud) or **IBM Granite 3.3 Vision / Qwen2-VL** (local) perform the actual receipt extraction inside the app.

Different models specialize in specific tasks — architectural planning, precise code execution, adversarial review, and OCR parsing — so no single model's weaknesses go unchecked.

## ⚡ Quick Start

### Prerequisites
- Python 3.11+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Google Gemini API Key **OR** a local model server ([LM Studio](https://lmstudio.ai/) or [Ollama](https://ollama.com/))

> [!TIP]
> **Getting a free Gemini API key** takes about a minute:
> 1. Go to [Google AI Studio](https://aistudio.google.com/apikey) and sign in with any Google account.
> 2. Click **Create API key** and copy the key.
> 3. Paste it into your `.env` as `GEMINI_API_KEY=...` (see step 1 below).
>
> The **free tier** is plenty for personal receipt volume — the app minimizes API calls with a rule-based fast path for digital PDFs, OCR result caching, and token-light text-paste ingestion. No credit card required.

### Setup

1.  **Clone & Configure**:
    ```bash
    git clone https://github.com/smcgarrigle/ihavethereceipts.git
    cd ihavethereceipts
    cp .env.example .env
    # Edit .env and pick an OCR backend:
    #   OCR_BACKEND=gemini    + GEMINI_API_KEY=your_key        (cloud)
    # or
    #   OCR_BACKEND=local     + OCR_MODEL=granite3.3-vision:2b (LM Studio/Ollama)
    #                         + OCR_BACKEND_URL=http://localhost:11434/v1
    ```

2.  **Install & Run**:
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
    ```bash
    # LM Studio: download from https://lmstudio.ai and load a Qwen2-VL or Granite model
    # Ollama:
    ollama pull granite3.3-vision:2b   # or qwen2-vl
    ```

4.  **Access App**: Open `http://127.0.0.1:8000`


## 🔀 OpenRouter Connector

Option 4 in `./start_server.sh` sends receipts through **your own** OpenRouter account, on a model you pick. It exists for people who already have OpenRouter credits and their own provider preferences — it is not a way to get free OCR, for reasons below.

There is deliberately **no default model**. OpenRouter serves hundreds at wildly different prices and capabilities, so the startup menu asks you to name one, and OCR fails with a clear message until you do.

```bash
# root .env
OCR_BACKEND=openrouter
OPENROUTER_API_KEY=sk-or-v1-...     # https://openrouter.ai/keys
OCR_MODEL=qwen/qwen-2.5-vl-72b-instruct   # any model that accepts image input
```

An account is required; a payment method is not. `OCR_BACKEND_URL` is ignored here — it points at your local Ollama/LM Studio, and honouring it would post receipts at a dead localhost port. Use `OPENROUTER_BASE_URL` if you genuinely proxy OpenRouter.

### Privacy

Every request carries `provider.data_collection=deny`, so OpenRouter refuses to route to providers that retain or train on inputs. This is enforced server-side rather than depending on your account settings. Receipts are still leaving your machine — if that matters, options 1 and 2 keep everything local.

### ⚠ The ":free" caveat

**Free models and the deny policy are mutually exclusive.** Measured against the live API on 2026-08-17: every free vision model returns `404 — No endpoints found matching your data policy (Free model training)`. Free models are free *because* the serving provider may train on what you send. There is no configuration that gives you both.

If you want to use them anyway, opt in explicitly:

```bash
OPENROUTER_ALLOW_TRAINING=1   # provider may retain and train on your receipts
```

With that set, quality is good — `nvidia/nemotron-nano-12b-v2-vl:free` extracted a test receipt perfectly (8/8 line items, store, date, subtotal, tax and total exact) in ~21s. But the free tier is capped at **20 requests/min and 50/day** until $10 of credits has been purchased, so bulk imports belong on a local backend. That endpoint also reported 76.7% 24-hour uptime, and one run returned an empty item list with no error at all — a silent miss is worse than a loud failure for background OCR.

Free *and* vision-capable is a short list; most free models are text-only and will return empty extractions rather than errors:

| Model | Context |
|---|---|
| `nvidia/nemotron-nano-12b-v2-vl:free` | 128K |
| `google/gemma-4-26b-a4b-it:free` | 256K |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | 256K |

### Billing guard

A model without the `:free` suffix is refused unless `OPENROUTER_ALLOW_PAID=1`. Choosing a paid model at the startup menu sets this for you — typing the ID is the deliberate act. The guard remains for anyone hand-editing `.env`. A `402` on a `:free` model means a negative balance, not an exhausted free tier.


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

1. `static/css/tailwind.css` only contains classes that existed in templates when it was last built. **After adding any new Tailwind class, re-run `./scripts/build_css.sh`** and commit the rebuilt CSS together with the template change — otherwise the class silently renders unstyled.
2. The content scan covers `templates/**/*.html`, `app/api/pages.py`, and `static/js/**/*.js`. If you embed Tailwind classes elsewhere, add that path to `content` in `tailwind.config.js`.
3. Dynamically constructed class names are invisible to the scanner — always write full literal class names, or add them to a `safelist`.
4. Do not swap Alpine.js for its CSP build or remove `'unsafe-eval'` from the CSP: the standard Alpine build evaluates inline expressions via `AsyncFunction`, and every modal/drawer/tab depends on it.

### Keeping Python dependencies up to date

The committed `uv.lock` keeps installs reproducible indefinitely. Refresh it deliberately (every few months, or after a CVE) rather than routinely, and always run the tests before committing the new lock.

```bash
cd backend

# Upgrade everything to latest compatible versions
uv lock --upgrade
uv sync --extra dev
uv run pytest && uv run ruff check . && uv run mypy .   # verify

# Or upgrade a single package
uv lock --upgrade-package fastapi
```

Commit the updated `uv.lock` after a successful test run.

> [!NOTE]
> For security auditing, run `uv run pip-audit` periodically. See [SBOM.md](SBOM.md) for the full dependency inventory.


## 🔮 Roadmap

See [ROADMAP.md](ROADMAP.md) for the full strategic backlog. Highlights:

- [ ] **Interactive Chart Filters**: Dropdown menus to filter charts by date, store, or category.
- [ ] **Barcode Scanning**: Mobile camera integration via OpenFoodFacts.
- [ ] **Volatility Alerts**: Notify when an item's price shifts >15% in 30 days.
- [ ] **Items Page Pagination**: Full paginated fragment to replace the current unbound item list.
- [ ] **PWA / Offline Mode**: Scan receipts in-store without connectivity.


## 🐧 Running on Linux (Ubuntu / Debian)

Install system dependencies before running `uv sync`:

```bash
# PDF processing + file-type detection
sudo apt install -y poppler-utils libmagic1

# Optional: local AI via Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull granite3.3-vision:2b   # or qwen2-vl
```

Then follow the standard [Setup](#setup) steps. The `Makefile` in the project root wraps common commands:

```bash
make setup   # uv sync + pre-commit install
make run     # start the dev server
make test    # run pytest suite
make lint    # ruff check + format
```

**Common Linux issues:**

| Issue | Resolution |
|---|---|
| `pdfplumber` fails to open PDFs | Run `sudo apt install poppler-utils` |
| `python-magic` import error | Run `sudo apt install libmagic1` |
| Port 8000 already in use | Change with `--port 8001` in `make run` |
| Ollama slow on first run | First inference downloads model weights — normal |
| SQLite `database is locked` | WAL mode is on by default; this is rare under normal use |

> [!NOTE]
> **WSL2 users**: The app runs fine under WSL2. Access it at `http://127.0.0.1:8000` in your Windows browser. For best performance, clone the repo into the WSL2 filesystem (`~/projects/`) rather than a Windows-mounted path (`/mnt/c/...`) — cross-filesystem I/O adds latency to file watching and uploads.


## 🍎 Running on Mac M1 / M2 (Apple Silicon)

The app runs natively on Apple Silicon. After cloning, install system dependencies first:

```bash
# Homebrew (if not installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install uv poppler libmagic   # uv + PDF + file-type detection

# Optional: local AI via Ollama
brew install ollama
ollama pull granite3.3-vision:2b   # or qwen2-vl
```

Then follow the standard [Setup](#setup) steps above. A `Makefile` in the project root also wraps common commands:

```bash
make setup   # uv sync + pre-commit install
make run     # start the dev server
make test    # run pytest suite
make lint    # ruff check + format
```

**Common Mac issues:**

| Issue | Resolution |
|---|---|
| `pdfplumber` fails to open PDFs | Run `brew install poppler` |
| `python-magic` import error | Run `brew install libmagic` |
| Port 8000 already in use | Change with `--port 8001` in `make run` |
| LM Studio / Ollama slow on first run | First inference downloads model weights — normal |
| SQLite `database is locked` | WAL mode is on by default; this is rare under normal use |

> [!TIP]
> The app defaults to **SQLite** (zero config). No extra database setup needed for single-user use on Mac.
