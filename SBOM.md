# Software Bill of Materials (SBOM)

**Project:** IHaveTheReceipts
**Version:** 0.1.0
**Generated:** 2026-08-05
**Format:** Markdown (manual, based on `uv pip list`)

---

## Runtime Environment

| Component | Version |
| :--- | :--- |
| **OS** | Ubuntu 22.04.5 LTS (Jammy Jellyfish) |
| **Python** | 3.12.12 (runtime) / 3.11+ (required by `pyproject.toml`) |
| **Package Manager** | [uv](https://github.com/astral-sh/uv) |

---

## Direct Dependencies

These are the packages explicitly declared in `backend/pyproject.toml`.

### Web Framework & Server

| Package | Installed Version | License | Purpose |
| :--- | :--- | :--- | :--- |
| [fastapi](https://fastapi.tiangolo.com/) | 0.128.0 | MIT | ASGI web framework |
| [uvicorn](https://www.uvicorn.org/) `[standard]` | 0.40.0 | BSD-3-Clause | ASGI server |
| [starlette](https://www.starlette.io/) | 0.50.0 | BSD-3-Clause | ASGI toolkit (FastAPI dependency) |
| [jinja2](https://jinja.palletsprojects.com/) | 3.1.6 | BSD-3-Clause | HTML templating engine |
| [python-multipart](https://github.com/andrew-d/python-multipart) | 0.0.21 | Apache-2.0 | Form/file upload parsing |
| [itsdangerous](https://itsdangerous.palletsprojects.com/) | 2.2.0 | BSD-3-Clause | CSRF token signing |
| [aiofiles](https://github.com/Tinche/aiofiles) | 25.1.0 | Apache-2.0 | Async file I/O |

### Database & ORM

| Package | Installed Version | License | Purpose |
| :--- | :--- | :--- | :--- |
| [sqlalchemy](https://www.sqlalchemy.org/) | 2.0.46 | MIT | ORM and query builder |
| [alembic](https://alembic.sqlalchemy.org/) | 1.18.1 | MIT | Database schema migrations |
| [psycopg2-binary](https://www.psycopg.org/) | 2.9.11 | LGPL-3.0 | PostgreSQL driver (sync) — legacy, unused |
| [asyncpg](https://github.com/MagicStack/asyncpg) | 0.31.0 | Apache-2.0 | PostgreSQL driver (async) — legacy, unused |

> **Primary database:** SQLite (zero-config, file-based). The PostgreSQL drivers (`psycopg2-binary`, `asyncpg`) are legacy artifacts from early development and are not required for normal operation. They are candidates for removal in a future cleanup.

### AI / OCR

| Package | Installed Version | License | Purpose |
| :--- | :--- | :--- | :--- |
| [google-genai](https://ai.google.dev/) | 1.60.0 | Apache-2.0 | Google Gemini API (primary OCR/AI) |
| [openai](https://github.com/openai/openai-python) | 2.28.0 | Apache-2.0 | OpenAI-compatible API client (local LM Studio / Ollama) |
| [pillow](https://python-pillow.org/) | 12.1.0 | HPND | Image manipulation for OCR pre-processing |
| [pdf2image](https://github.com/Belval/pdf2image) | 1.17.0 | MIT | PDF → image conversion for OCR |
| [pdfplumber](https://github.com/jsvine/pdfplumber) | 0.11.9 | MIT | PDF text extraction (digital receipts) |

### String Matching & Data Quality

| Package | Installed Version | License | Purpose |
| :--- | :--- | :--- | :--- |
| [rapidfuzz](https://github.com/maxbachmann/RapidFuzz) | 3.14.3 | MIT | Fast fuzzy string matching (item deduplication) — **preferred** |
| [fuzzywuzzy](https://github.com/seatgeek/fuzzywuzzy) | 0.18.0 | GPL-2.0 | Legacy fuzzy match — **superseded by rapidfuzz, pending removal** |
| [python-levenshtein](https://github.com/maxbachmann/python-Levenshtein) | 0.27.3 | GPL-2.0 | Edit-distance computations — **pending removal** |
| [json-repair](https://github.com/mangiucugna/json_repair) | 0.58.6 | MIT | Repairs malformed JSON from LLM output |

### Data Processing & Export

| Package | Installed Version | License | Purpose |
| :--- | :--- | :--- | :--- |
| [pandas](https://pandas.pydata.org/) | 3.0.2 | BSD-3-Clause | Data manipulation and export logic |
| [openpyxl](https://openpyxl.readthedocs.io/) | 3.1.5 | MIT | Excel (.xlsx) export |
| [numpy](https://numpy.org/) | 2.4.4 | BSD-3-Clause | Numerical computations (analytics, pandas dependency) |

### HTTP & Configuration

| Package | Installed Version | License | Purpose |
| :--- | :--- | :--- | :--- |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | 1.2.1 | BSD-3-Clause | `.env` file loading |
| [httpx](https://www.python-httpx.org/) | 0.28.1 | BSD-3-Clause | Async HTTP client (FDC API, external enrichment) |
| [requests](https://requests.readthedocs.io/) | 2.32.5 | Apache-2.0 | Sync HTTP client (model manager, legacy endpoints) |
| [pydantic](https://docs.pydantic.dev/) | 2.12.5 | MIT | Data validation and settings management |

---

## Development & Tooling Dependencies

These packages are declared in `[project.optional-dependencies] dev` in `pyproject.toml` and are only installed when contributors run `uv sync --extra dev`. End users running the app do not need them.

| Package | Installed Version | License | Purpose |
| :--- | :--- | :--- | :--- |
| [ruff](https://docs.astral.sh/ruff/) | 0.15.12 | MIT | Linter + formatter (replaces flake8/black/isort) |
| [mypy](https://mypy-lang.org/) | 2.0.0 | MIT | Static type checker |
| [pre-commit](https://pre-commit.com/) | 4.6.0 | MIT | Git pre-commit hook runner |
| [pytest](https://pytest.org/) | 9.0.3 | MIT | Test framework (255 collected, 245 active) |
| [pytest-asyncio](https://pytest-asyncio.readthedocs.io/) | 1.3.0 | Apache-2.0 | Async test support |
| [playwright](https://playwright.dev/python/) | 1.60.0 | Apache-2.0 | Browser automation (E2E UI tests — deselected by default) |
| [beautifulsoup4](https://www.crummy.com/software/BeautifulSoup/) | 4.15.0 | MIT | HTML parsing for template/accessibility tests |
| [axe-core-python](https://github.com/nicholasgasior/axe-core-python) | 0.1.0 | MPL-2.0 | Accessibility (a11y) assertions in tests |
| [types-pillow](https://pypi.org/project/types-Pillow/) | 10.2.0.20240822 | Apache-2.0 | Mypy type stubs for Pillow |

> **Mypy status (August 2026):** The pre-commit mypy gate is active. A ratchet override in `pyproject.toml [tool.mypy.overrides]` suppresses errors in 9 legacy API modules while they are progressively cleaned. All other modules are fully checked on every commit.

---

## Frontend (Vendored locally — `backend/static/`)

All frontend libraries are downloaded and served locally. No external CDN requests are made at runtime. This enables fully offline operation and eliminates CSP violations from blocked CDN hosts.

| Library | Pinned Version | License | Purpose | Location |
| :--- | :--- | :--- | :--- | :--- |
| [Tailwind CSS](https://tailwindcss.com/) | 3.4.17 (standalone CLI) | MIT | Utility-first CSS — precompiled to `static/css/tailwind.css` by `scripts/build_css.sh`. The browser Play CDN runtime is not used. | `static/css/tailwind.css` |
| [HTMX](https://htmx.org/) | 1.9.10 | BSD-2-Clause | Server-driven HTML fragments / AJAX | `static/js/vendor/htmx.min.js` |
| [Alpine.js](https://alpinejs.dev/) | 3.x | MIT | Lightweight client-side reactivity | `static/js/vendor/alpine.min.js` |
| [Alpine.js Collapse](https://alpinejs.dev/plugins/collapse) | 3.x | MIT | Collapse/expand animation plugin | `static/js/vendor/alpine-collapse.min.js` |
| [Alpine.js Focus](https://alpinejs.dev/plugins/focus) | 3.x | MIT | Focus trapping for accessible modals | `static/js/vendor/alpine-focus.min.js` |
| [Chart.js](https://www.chartjs.org/) | 4.4.0 | MIT | Data visualization / analytics charts | `static/js/vendor/chart.umd.min.js` |
| [Inter](https://rsms.me/inter/) | v20 | OFL-1.1 | UI typeface, vendored woff2 (latin + latin-ext) | `static/fonts/` |

> ✅ **Offline-safe**: All assets served from `/static/`. No internet required at runtime.
> 🔒 **CSP**: `SecurityHeadersMiddleware` is configured to match this fully-vendored setup. No external font or CDN origins are required.

---

## Notable Transitive Dependencies

| Package | Installed Version | Notes |
| :--- | :--- | :--- |
| [uvloop](https://github.com/MagicStack/uvloop) | 0.22.1 | High-performance event loop (uvicorn `[standard]`) |
| [watchfiles](https://watchfiles.helpmanual.io/) | 1.1.1 | Hot-reload file watching (uvicorn `[standard]`) |
| [websockets](https://websockets.readthedocs.io/) | 15.0.1 | WebSocket support (uvicorn `[standard]`) |
| [pydantic-core](https://github.com/pydantic/pydantic-core) | 2.41.5 | Rust-based core for pydantic v2 |
| [google-auth](https://google-auth.readthedocs.io/) | 2.47.0 | Auth for Google Gemini API |
| [mako](https://www.makotemplates.org/) | 1.3.10 | Templating engine (alembic migrations) |
| [pdfminer-six](https://pdfminersix.readthedocs.io/) | 20251230 | PDF text extraction (pdfplumber dependency) |
| [pypdfium2](https://pypdfium2.readthedocs.io/) | 5.6.0 | PDF rendering (pdfplumber dependency) |
| [cryptography](https://cryptography.io/) | 46.0.6 | Crypto primitives (google-auth dependency) |
| [anyio](https://anyio.readthedocs.io/) | 4.12.1 | Async compatibility layer (httpx / fastapi) |
| [tenacity](https://tenacity.readthedocs.io/) | 9.1.2 | Retry logic (google-genai dependency) |
| [httpx](https://www.python-httpx.org/) | 0.28.1 | HTTP client (openai / google-genai dependency) |

---

## License Summary

| License | Count | Key Packages |
| :--- | :--- | :--- |
| MIT | ~20 | fastapi, sqlalchemy, alembic, rapidfuzz, json-repair, ruff, pytest, openpyxl |
| Apache-2.0 | ~10 | google-genai, openai, asyncpg, aiofiles, playwright, requests |
| BSD-3-Clause | ~8 | uvicorn, starlette, jinja2, python-dotenv, pandas, numpy, httpx |
| GPL-2.0 | 2 | fuzzywuzzy, python-levenshtein (**pending removal**) |
| LGPL-3.0 | 1 | psycopg2-binary (legacy, unused) |
| MPL-2.0 | 1 | axe-core-python (dev only) |
| HPND | 1 | pillow |
| OFL-1.1 | 1 | Inter font (vendored) |

> ⚠️ **GPL-2.0 note:** `fuzzywuzzy` and `python-levenshtein` are GPL-2.0. They are used internally only (not redistributed as a library). `rapidfuzz` (MIT) is the established replacement — all new matching code uses it. These two packages should be removed from `pyproject.toml` once any remaining call sites are audited and migrated.

---

## Generating a Fresh SBOM

```bash
# From the backend directory
cd backend
uv pip list --format=columns

# Or for JSON output suitable for automated tooling
uv pip list --format=json
```

---

*Last Updated: August 5, 2026*
