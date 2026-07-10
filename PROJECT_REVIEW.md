# Grocery Tracker — Product & Engineering Review

*Reviewed: 2026-07-03 | Basis: full codebase read, live database inspection (320 receipts, 1,266 items, 76 commits), and a test-suite run (56/57 passing).*

---

## Scorecard

| Dimension | Score | One-liner |
|---|:---:|---|
| Engineering | **7.5 / 10** | Solid service architecture, real tests, hardened middleware — held back by oversized modules and sync/async confusion |
| Design (UI/UX) | **8 / 10** | Genuinely polished low-JS stack with theming and Tufte-styled charts; CSP is looser than the vendored-asset story deserves |
| Utility | **8.5 / 10** | Solves a real problem daily — price history, restock prediction, and store comparison over 320 real receipts |
| Use of AI | **8.5 / 10** | Dual-backend OCR with human-in-the-loop sandbox and a rule-based fast path is thoughtful, pragmatic AI engineering |
| Nutritional data | **5.5 / 10** | The pipeline is well-designed but nearly empty: only 8% of items have nutrient data, so downstream charts run on a sliver of reality |
| **Overall** | **7.5 / 10** | A strong, real product with one under-fed subsystem and some structural debt |

---

## Engineering — 7.5/10

**What's strong**

- Clean separation of concerns: 14 API routers, 16 focused services (`item_matcher`, `category_mapper`, `model_manager`, `bulk_processor`), 6 models. The service layer is where the intelligence lives, and it's mostly the right size.
- Real security posture for a self-hosted app: CSRF middleware (header + form token), rate limiting on upload endpoints, 15MB body limit, security headers + CSP, fail-fast secret handling. This is more than most hobby projects bother with.
- 57 tests across 21 files covering the risky parts (OCR merging, unit-price math, duplicate flow, template integrity). 56/57 pass; the single failure is a Playwright browser-availability issue, not a code bug.
- Modern toolchain: `uv` + lockfile, Ruff, Mypy, pre-commit, Alembic, SBOM and security docs.
- Operational care: startup cleanup of orphaned "processing" receipts, WAL mode, singleton `BulkProcessor` with graceful shutdown, OCR result caching.

**What holds it back**

1. **Oversized modules.** `analytics.py` (1,972 lines), `trends.py` (1,221), `receipts.py` (1,110), `main.py` (1,005). `main.py` should be app wiring only; it's carrying page routes.
2. **Sync/async mismatch.** The README claims "SQLAlchemy (Async)" but the code uses sync `db.query(...)` sessions inside `async def` FastAPI handlers, and services make blocking HTTP calls (`requests` in `fdc_service`, `urllib` with up-to-5 retries at 15s timeout in `external_product`) — each of these blocks the event loop when called from async paths.
3. **Dual schema management.** `Base.metadata.create_all()` runs at import time in `main.py` alongside Alembic. One of them is lying; new environments can silently diverge from migration history.
4. **In-memory rate limiter grows unbounded** per unique IP and resets on restart — fine for single-user, but it's security theater beyond that.
5. **O(n²)-ish enrichment propagation**: `fdc_service.enrich_db_item` loads *all* items and fuzzy-scores each one on every enrichment call.
6. **Repo hygiene**: live database (`grocery.db` + WAL/SHM), `recover.sql`, a receipts ZIP, `uvicorn.log`, and a `Zone.Identifier` file at the root; 13 files uncommitted; two `scratch/` trees with ~40 one-off scripts. Also a known `SAWarning` (subquery coerced in `IN()`) in `trends.py:1048`.

## Design — 8/10

**What's strong**

- The HTMX + Alpine.js "low-JS" architecture is the right call for this product — server-rendered fragments, no build step, snappy interactions.
- Multi-theme engine (Light/Dark/Forest/Sunset) via CSS variables, mobile-first layouts, collapsible drawers, and a style guide page — real design-system thinking.
- Tufte-inspired chart treatment (ghost gridlines, shared Chart.js defaults, sparkline grids) is distinctive and appropriate for a data-dense product.
- All frontend runtime dependencies vendored into `static/js/vendor/` — the app works fully offline.

**What holds it back**

1. **The vendored Tailwind is the Play CDN runtime** (`tailwind.min.js`), which compiles classes in the browser and forces `'unsafe-eval'` + `'unsafe-inline'` into the CSP. The CSP also still allowlists `cdn.tailwindcss.com`, `unpkg.com`, `jsdelivr`, and Google Fonts, undercutting the offline-first/hardening story.
2. **Monster templates** — the largest pages carry heavy inline Alpine state and script blocks, making UI changes risky (the test suite even needs a `test_template_integrity.py`).
3. Known UX papercuts already on the roadmap: PDF `<embed>` swallowing Esc in the review modal, full-page navigations on mobile where drawers would preserve context.

## Utility — 8.5/10

This is the strongest dimension because the product is *used*: 320 real receipts and 1,266 items of genuine purchase history. The feature set compounds well — price history per item, store comparison, restock prediction from purchase cadence, a store-optimized shopping list, CSV/Excel export, and a demo seeder for new users. The human-in-the-loop review sandbox directly addresses the actual failure mode of receipt OCR (store-specific discount dialects), which shows product judgment, not just feature-listing.

Deductions: single-user only (no household support), no in-store capture path (no PWA/offline scanning, no barcode input), and insight quality depends on manual review discipline — friction that compounds with volume. The 163-category fragmentation problem (acknowledged in the roadmap) dilutes the analytics the product exists to provide.

## Use of AI — 8.5/10

**What's strong**

- **Dual-backend OCR** (Gemini API or fully local via Ollama/LM Studio) with runtime backend switching — privacy and cost flexibility most projects never attempt.
- **The hybrid fast path**: rule-based `pdfplumber` parsing for digital receipts (Amazon, iHerb) skips the LLM entirely — 100% fidelity, zero cost. Knowing when *not* to use AI is the mark of good AI engineering.
- **A battle-hardened prompt**: the 11-rule receipt prompt encodes real-world lessons (CRV/deposit handling, "Price vs You Pay" columns, packaged-weight extraction, Whole Foods–via–Amazon attribution) — clearly iterated against real failures.
- Defensive plumbing: `json-repair` for malformed model output, daily usage tracking with thread-safe caching, OCR response caching, model-manager fallback, and a sanity check reconciling line items against receipt subtotals.

**What holds it back**

1. **No feedback loop.** Human corrections in the review sandbox are discarded as training signal. The roadmap's "dynamic few-shot" idea (inject past corrections from the same store into the prompt) is the single highest-leverage AI improvement available.
2. **No structured output enforcement** — prompt-and-pray JSON instead of Gemini's response-schema / structured output mode, which would eliminate most `json-repair` work on the API path.
3. **No evaluation harness.** There's no labeled receipt set to measure extraction accuracy across models, so model/prompt changes are vibes-tested.

## Nutritional data — 5.5/10

**What's strong**

- The architecture is genuinely good: dual-source enrichment (USDA FDC + OpenFoodFacts), OCR-noise query cleaning with abbreviation expansion, fuzzy best-match with weighted scoring, category propagation to similar items, per-100g macro scaling with unit conversion, macro-dominance classification, and manual-override columns (`custom_nutrients`, `nutrition_source`) already migrated into the schema.
- The Tufte-styled trends visualizations (caloric profile, DV bullet graphs, nutrient sparklines) are ready to shine — once data exists.

**Why the score is low: the pipeline is starving.** Live database numbers:

| Metric | Count | Coverage |
|---|---:|---:|
| Items total | 1,266 | — |
| FDC ID matched | 216 | 17% |
| Actual nutrient data (`nutrients` JSON) | 101 | **8%** |
| OpenFoodFacts code | 1 | ~0% |
| Manual overrides (`custom_nutrients`) | 0 | 0% |
| Nutriscore | 1 | ~0% |

Every nutrition chart is computed from ~8% of the pantry, silently. Two structural problems compound the coverage gap:

1. **Discrete items are invisible.** `calculate_receipt_item_macros` requires a `weight` + `unit_type` on the receipt line, so anything bought by count (a jar, a box, a 6-pack) contributes zero — biasing all nutrition analytics toward bulk produce and meat.
2. **Purchases ≠ intake.** The charts implicitly read as dietary intake, but the data is *what entered the house*. That's still interesting (it's arguably a better honesty signal than a food diary) — but the UI should frame it as "nutritional profile of your shopping," and nothing currently discloses the 8% coverage.

---

## Remediation Plan

### Phase 1 — Feed the nutrition pipeline (highest impact-to-effort)

1. **Run the full FDC sweep** (already a roadmap item, and `scripts/backfill_nutrients.py` exists): batch-match all 1,266 items, fetching *full nutrient payloads* — not just `fdc_id` — so `nutrients` coverage rises from 8% toward the 17%+ already matched. Rate-limit and checkpoint so it can run overnight.
2. **Add a package-size fallback for discrete items**: the OCR already extracts sizes from names ("16OZ", "5LB"); when a receipt line has no weight, derive grams from `quantity × package size`, falling back to FDC `servingSize × servingsPerContainer`. This fixes the discrete-item blind spot in `nutrition_utils.calculate_receipt_item_macros`.
3. **Surface coverage honestly**: every nutrition chart gets a "based on N% of items by spend" badge, and the trends page links to the FDC match queue for the biggest unmatched spend drivers.
4. **Wire up the manual override UI** end-to-end: `custom_nutrients` / `nutrition_source` columns exist but hold zero rows — prioritize the top-20 items by spend so hand-fixing them moves the charts materially.
5. **Reframe copy** from "your nutrition" to "nutritional profile of your purchases."

### Phase 2 — Structural engineering debt

6. **Split the big four modules**: extract page routes out of `main.py` into a `pages` router; break `analytics.py` and `trends.py` into per-domain modules (spend, categories, nutrition, predictions).
7. **Resolve sync/async**: either adopt async SQLAlchemy + `httpx.AsyncClient` for FDC/OFF calls, or run blocking work via `run_in_threadpool` — and correct the README's "SQLAlchemy (Async)" claim until true.
8. **Pick one schema authority**: drop `Base.metadata.create_all()` and run `alembic upgrade head` at startup (or behind a flag).
9. **Repo hygiene**: gitignore/remove `grocery.db*`, `uvicorn.log`, `recover.sql`, the receipts ZIP, and `*.Zone.Identifier`; archive the two `scratch/` trees; commit or triage the 13 dirty files.
10. Fix the `trends.py:1048` `SAWarning` (pass a `select()` into `IN()`), and bound the rate-limiter dict (e.g., LRU cap or periodic sweep).

### Phase 3 — AI compounding loop

11. **Dynamic few-shot from corrections**: persist review-sandbox diffs (AI output vs. human-approved) per store, and inject the most recent corrections for that store into the OCR prompt. This turns every manual fix into permanent accuracy gains.
12. **Structured outputs on the Gemini path** (response schema) to eliminate JSON repair on the API backend; keep `json-repair` for local models.
13. **Build a small eval set**: ~20 labeled receipts spanning stores/formats, plus a script scoring item-count, total, and per-line accuracy — so model and prompt changes become measurable.

### Phase 4 — Design & utility polish

14. **Replace the Tailwind Play runtime with a precompiled CSS build** (standalone Tailwind CLI, no Node required); then drop `unsafe-eval` and the CDN hosts from the CSP.
15. **Category taxonomy collapse** (roadmap item #1): the 163-category fragmentation directly degrades the analytics that make the product useful — do it before adding new chart types.
16. **In-store capture path**: PWA + camera upload (or at minimum the folder-watch ingester) to remove the biggest utility friction — getting receipts into the system.

---

*Bottom line: this is a real product with unusually mature AI plumbing for a self-hosted tool. The nutrition subsystem isn't badly built — it's badly fed. One overnight backfill, a package-size fallback, and honest coverage labeling would likely move that 5.5 to a 7+ without touching the architecture.*
