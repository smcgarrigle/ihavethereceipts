# Software Bill of Materials (SBOM)

**Project:** IHaveTheReceipts
**Version:** 0.1.0
**Generated:** 2026-09-08
**Format:** Markdown. Versions are derived from `backend/uv.lock` by
`backend/scripts/refresh_sbom.py`; licence and purpose are maintained by hand.
`tests/test_sbom_current.py` fails when the versions drift.

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
| [fastapi](https://fastapi.tiangolo.com/) | 0.141.1 | MIT | ASGI web framework |
| [uvicorn](https://www.uvicorn.org/) `[standard]` | 0.52.1 | BSD-3-Clause | ASGI server |
| [starlette](https://www.starlette.io/) | 1.4.1 | BSD-3-Clause | ASGI toolkit (FastAPI dependency) |
| [jinja2](https://jinja.palletsprojects.com/) | 3.1.6 | BSD-3-Clause | HTML templating engine |
| [python-multipart](https://github.com/andrew-d/python-multipart) | 0.0.32 | Apache-2.0 | Form/file upload parsing |
| [itsdangerous](https://itsdangerous.palletsprojects.com/) | 2.2.0 | BSD-3-Clause | CSRF token signing |

### Database & ORM

| Package | Installed Version | License | Purpose |
| :--- | :--- | :--- | :--- |
| [sqlalchemy](https://www.sqlalchemy.org/) | 2.0.51 | MIT | ORM and query builder |
| [alembic](https://alembic.sqlalchemy.org/) | 1.19.0 | MIT | Database schema migrations |

> **Primary database:** SQLite (zero-config, file-based). The PostgreSQL drivers that used to be declared here were removed once a check confirmed they had no import sites anywhere.

### AI / OCR

| Package | Installed Version | License | Purpose |
| :--- | :--- | :--- | :--- |
| [google-genai](https://ai.google.dev/) | 2.17.0 | Apache-2.0 | Google Gemini API (primary OCR/AI) |
| [openai](https://github.com/openai/openai-python) | 2.53.0 | Apache-2.0 | OpenAI-compatible API client (local LM Studio / Ollama) |
| [pillow](https://python-pillow.org/) | 12.3.0 | HPND | Image manipulation for OCR pre-processing |
| [pdf2image](https://github.com/Belval/pdf2image) | 1.17.0 | MIT | PDF → image conversion for OCR |
| [pdfplumber](https://github.com/jsvine/pdfplumber) | 0.11.10 | MIT | PDF text extraction (digital receipts) |

### String Matching & Data Quality

| Package | Installed Version | License | Purpose |
| :--- | :--- | :--- | :--- |
| [rapidfuzz](https://github.com/maxbachmann/RapidFuzz) | 3.14.5 | MIT | Fast fuzzy string matching (item deduplication) — **preferred** |
| [json-repair](https://github.com/mangiucugna/json_repair) | 0.62.0 | MIT | Repairs malformed JSON from LLM output |

### Data Processing & Export

| Package | Installed Version | License | Purpose |
| :--- | :--- | :--- | :--- |
| [pandas](https://pandas.pydata.org/) | 3.0.5 | BSD-3-Clause | Data manipulation and export logic |
| [openpyxl](https://openpyxl.readthedocs.io/) | 3.1.5 | MIT | Excel (.xlsx) export |
| [numpy](https://numpy.org/) | 2.5.1 | BSD-3-Clause | Numerical computations (analytics, pandas dependency) |

### HTTP & Configuration

| Package | Installed Version | License | Purpose |
| :--- | :--- | :--- | :--- |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | 1.2.2 | BSD-3-Clause | `.env` file loading |
| [httpx](https://www.python-httpx.org/) | 0.28.1 | BSD-3-Clause | Async HTTP client (FDC API, external enrichment) |
| [requests](https://requests.readthedocs.io/) | 2.34.2 | Apache-2.0 | Sync HTTP client (model manager, legacy endpoints) |
| [pydantic](https://docs.pydantic.dev/) | 2.13.4 | MIT | Data validation and settings management |

---

## Development & Tooling Dependencies

These packages are declared in `[project.optional-dependencies] dev` in `pyproject.toml` and are only installed when contributors run `uv sync --extra dev`. End users running the app do not need them.

| Package | Installed Version | License | Purpose |
| :--- | :--- | :--- | :--- |
| [ruff](https://docs.astral.sh/ruff/) | 0.16.1 | MIT | Linter + formatter (replaces flake8/black/isort) |
| [mypy](https://mypy-lang.org/) | 2.3.0 | MIT | Static type checker |
| [pre-commit](https://pre-commit.com/) | 4.6.1 | MIT | Git pre-commit hook runner |
| [pytest](https://pytest.org/) | 9.1.1 | MIT | Test framework (255 collected, 245 active) |
| [pytest-asyncio](https://pytest-asyncio.readthedocs.io/) | 1.4.0 | Apache-2.0 | Async test support |
| [playwright](https://playwright.dev/python/) | 1.62.0 | Apache-2.0 | Browser automation (E2E UI tests — deselected by default) |
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
| [watchfiles](https://watchfiles.helpmanual.io/) | 1.2.0 | Hot-reload file watching (uvicorn `[standard]`) |
| [websockets](https://websockets.readthedocs.io/) | 16.1.1 | WebSocket support (uvicorn `[standard]`) |
| [pydantic-core](https://github.com/pydantic/pydantic-core) | 2.46.4 | Rust-based core for pydantic v2 |
| [google-auth](https://google-auth.readthedocs.io/) | 2.56.2 | Auth for Google Gemini API |
| [mako](https://www.makotemplates.org/) | 1.4.1 | Templating engine (alembic migrations) |
| [pdfminer-six](https://pdfminersix.readthedocs.io/) | 20260107 | PDF text extraction (pdfplumber dependency) |
| [pypdfium2](https://pypdfium2.readthedocs.io/) | 5.12.1 | PDF rendering (pdfplumber dependency) |
| [cryptography](https://cryptography.io/) | 50.0.0 | Crypto primitives (google-auth dependency) |
| [anyio](https://anyio.readthedocs.io/) | 4.14.2 | Async compatibility layer (httpx / fastapi) |
| [tenacity](https://tenacity.readthedocs.io/) | 9.1.4 | Retry logic (google-genai dependency) |
| [httpx](https://www.python-httpx.org/) | 0.28.1 | HTTP client (openai / google-genai dependency) |

---

## License Summary

| License | Count | Key Packages |
| :--- | :--- | :--- |
| MIT | ~20 | fastapi, sqlalchemy, alembic, rapidfuzz, json-repair, ruff, pytest, openpyxl |
| Apache-2.0 | ~10 | google-genai, openai, playwright, requests, tenacity |
| BSD-3-Clause | ~8 | uvicorn, starlette, jinja2, python-dotenv, pandas, numpy, httpx |
| MPL-2.0 | 1 | axe-core-python (dev only) |
| HPND | 1 | pillow |
| OFL-1.1 | 1 | Inter font (vendored) |

> **No copyleft dependencies.** The two GPL-2.0 packages (`fuzzywuzzy`, `python-levenshtein`) and the LGPL-3.0 one (`psycopg2-binary`) were removed once a check confirmed none of them had an import site anywhere. Fuzzy matching is `rapidfuzz` (MIT) throughout.

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
