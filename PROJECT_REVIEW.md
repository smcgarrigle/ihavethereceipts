# Grocery Tracker — Product & Engineering Review

*Originally reviewed: 2026-07-03. Re-reviewed: 2026-07-10 | Basis: full codebase read, live database inspection (341 receipts, 1,460 items, 3,237 line items), and a test-suite run (83 passed, 1 deselected).*

> **What changed in a week:** all four phases of the original remediation plan shipped. Nutrition coverage went from 8% to 43% of items (41% of spend), the OCR feedback loop / structured outputs / eval harness all landed, the big modules were split, Alembic became the sole schema authority, and the Tailwind Play runtime was replaced with a precompiled build. Scores updated below; the original findings are preserved with their current status.

---

## Scorecard

| Dimension | Was | Now | One-liner |
|---|:---:|:---:|---|
| Engineering | 7.5 | **8.5 / 10** | Modules split, single schema authority, typed SQLAlchemy 2.0 models, 83 passing tests — remaining debt is minor and known |
| Design (UI/UX) | 8 | **8.5 / 10** | Precompiled Tailwind killed the Play-CDN runtime; CSP is tighter (one documented `unsafe-eval` exception for Alpine) |
| Utility | 8.5 | **9 / 10** | Text-paste ingestion, folder-watch auto-import, full export, and one-click data deletion round out a product used daily |
| Use of AI | 8.5 | **9 / 10** | The three gaps (feedback loop, structured outputs, eval harness) are all closed — corrections now compound into accuracy |
| Nutritional data | 5.5 | **7.5 / 10** | Coverage 8% → 43% of items, honest coverage badging, and a manual-entry path; still under half the pantry |
| **Overall** | 7.5 | **8.5 / 10** | The under-fed subsystem got fed and the structural debt got paid — what remains is polish, not repair |

---

## Engineering — 8.5/10 (was 7.5)

**What's strong**

- Clean separation of concerns: focused API routers and services (`item_matcher`, `category_mapper`, `model_manager`, `bulk_processor`). The service layer is where the intelligence lives, and it's mostly the right size.
- Real security posture for a self-hosted app: CSRF middleware (header + form token), rate limiting on upload endpoints, 15MB body limit, security headers + CSP, fail-fast secret handling.
- **83 tests passing** (up from 56) across the risky parts (OCR merging, unit-price math, duplicate flow, template integrity), and the suite is now fully isolated — it no longer touches the live DB or calls Gemini.
- Modern toolchain: `uv` + lockfile, Ruff, Mypy (now with a ratchet — errors can only go down), pre-commit, Alembic, SBOM and security docs. Models migrated to SQLAlchemy 2.0 typed `Mapped[]` style.
- Operational care: startup cleanup of orphaned "processing" receipts, WAL mode, singleton `BulkProcessor` with graceful shutdown, OCR result caching.

**Original findings — status**

1. ~~**Oversized modules.**~~ ✅ **Fixed.** `main.py` is 188 lines of app wiring (was 1,005) — page routes live in `api/pages.py`. `analytics.py` 1,972 → 986, `trends.py` 1,221 → 800 (nutrition split into `trends_nutrition.py`), `receipts.py` 1,110 → 544 (fragments/review split out).
2. **Sync/async mismatch.** ⚠️ **Half fixed.** The README now honestly documents synchronous sessions running in FastAPI's threadpool (the false "Async" claim is gone). Enrichment services still make blocking HTTP calls (`requests` in `fdc_service`, `urllib` in `external_product`), but these run inside background tasks, not request handlers — derisked, not eliminated.
3. ~~**Dual schema management.**~~ ✅ **Fixed.** `Base.metadata.create_all()` is gone; startup runs `alembic upgrade head`. Alembic is the sole schema authority.
4. ~~**Unbounded rate limiter.**~~ ✅ **Fixed.** The limiter now caps tracked clients (default 1,024) and sweeps idle IPs when the dict outgrows the cap.
5. **O(n²)-ish enrichment propagation.** ⚠️ **Still present** — the post-OCR pipeline loads all items and fuzzy-scores each; acceptable at 1,460 items, worth revisiting past ~10k.
6. ~~**Repo hygiene.**~~ ✅ **Fixed.** `grocery.db*`, `uvicorn.log`, `recover.sql`, and scratch trees are gitignored; working tree is clean; history was deliberately squashed. The `trends.py` `SAWarning` was fixed alongside a text-paste race condition.

## Design — 8.5/10 (was 8)

**What's strong**

- The HTMX + Alpine.js "low-JS" architecture is the right call for this product — server-rendered fragments, no build step at runtime, snappy interactions.
- Multi-theme engine (Light/Dark/Forest/Sunset) via CSS variables, mobile-first layouts, collapsible drawers, and a style guide page — real design-system thinking.
- Tufte-inspired chart treatment (ghost gridlines, shared Chart.js defaults, sparkline grids) is distinctive and appropriate for a data-dense product.
- All frontend runtime dependencies vendored — the app works fully offline.

**Original findings — status**

1. ~~**Tailwind Play runtime in the CSP.**~~ ✅ **Mostly fixed.** Tailwind is now precompiled via the standalone CLI (`scripts/build_css.sh`, no Node required) and the CDN hosts are out of the CSP. One deliberate exception remains: `'unsafe-eval'` stays because the standard Alpine.js build evaluates inline expressions via `AsyncFunction` — swapping to Alpine's CSP build would break every modal/drawer/tab. This trade-off is documented in the README.
2. **Monster templates** — the largest pages still carry heavy inline Alpine state; `test_template_integrity.py` remains the guardrail. Unchanged, still the main design debt.
3. Known UX papercuts (PDF `<embed>` swallowing Esc, full-page navigations on mobile) remain on the roadmap.

## Utility — 9/10 (was 8.5)

The product is *used*: 341 real receipts and 1,460 items of genuine purchase history. The feature set compounds well — price history per item, store comparison, restock prediction, a store-optimized shopping list, and a demo seeder.

**New since the original review**

- **Text-paste ingestion**: paste an order-confirmation email or digital receipt as plain text — no screenshot, no PDF. Cheaper and faster than image OCR (no vision tokens), and it makes digital-first stores nearly frictionless.
- **Folder-watch auto-import**: drop PDFs into `data/inbox` and they ingest themselves — the roadmap's "biggest utility friction" item, done.
- **Data ownership, both directions**: full export (per-receipt or entire history, CSV/Excel) and a one-click delete-everything endpoint in Settings. For a self-hosted personal-data app, easy exit matters as much as easy entry.
- **13-category taxonomy** (was 163): the category fragmentation that diluted every analytics view is collapsed.

Remaining deductions: single-user only (no household support) and no in-store capture path (no PWA/offline scanning, no barcode input).

## Use of AI — 9/10 (was 8.5)

**What's strong**

- **Dual-backend OCR** (Gemini API or fully local via Ollama/LM Studio) with runtime backend switching — privacy and cost flexibility most projects never attempt.
- **The hybrid fast path**: rule-based `pdfplumber` parsing for digital receipts skips the LLM entirely. Knowing when *not* to use AI is the mark of good AI engineering.
- **A battle-hardened prompt** encoding real-world lessons (CRV/deposit handling, "Price vs You Pay" columns, packaged-weight extraction, Whole Foods–via–Amazon attribution).
- Defensive plumbing: `json-repair` for local-model output, usage tracking, OCR response caching keyed on image **and prompt** (so learned corrections invalidate stale cache), model-manager fallback.

**Original findings — status: all three closed**

1. ~~**No feedback loop.**~~ ✅ **Shipped.** Review-sandbox corrections (renames, price fixes, missed items) are persisted per store and injected into future OCR prompts as few-shot examples. Every manual fix is now a permanent accuracy gain.
2. ~~**No structured output enforcement.**~~ ✅ **Shipped.** The Gemini path uses a Pydantic response schema for contractually valid JSON (with graceful fallback if a model rejects it); `json-repair` remains for local models, where it belongs.
3. ~~**No evaluation harness.**~~ ✅ **Shipped.** `scripts/ocr_eval.py` scores extraction accuracy against your own reviewed receipts (`--stored` for a free baseline, `--live` to benchmark prompt or model changes). Model and prompt changes are now measurable, not vibes-tested.

## Nutritional data — 7.5/10 (was 5.5)

**The turnaround.** The original review's diagnosis was "well-designed but nearly empty" — 8% coverage. The Phase 1 plan (backfill, package-size fallback, honest labeling, manual overrides) shipped. Current live numbers:

| Metric | Was (07-03) | Now (07-10) | Coverage |
|---|---:|---:|---:|
| Items total | 1,266 | 1,460 | — |
| FDC ID matched | 216 (17%) | 680 | **47%** |
| Actual nutrient data (`nutrients` JSON) | 101 (8%) | 623 | **43%** |
| Share of *spend* with nutrient data | ~8% | — | **41%** |

**What shipped**

- **The FDC backfill** ran, more than quintupling nutrient coverage.
- **Package-size fallback**: discrete items (jars, boxes, 6-packs) are no longer invisible — sizes embedded in item names ("16OZ", "5LB") feed the macro math, fixing the bias toward bulk produce and meat.
- **Honest coverage labeling**: the trends page shows a live coverage badge (share of spend with nutrient data for the selected time range) that links to the X-Ray match queue — the "silently computed from 8% of reality" problem is gone. Users can toggle visibility of the data gap instead of being misled by it.
- **User-entered nutrition data**: the manual-override path is now wired end-to-end. From an item's insights page you can enter or correct nutrition facts directly; values land in `custom_nutrients`, take precedence over API data when merged, and flow into every downstream chart. When USDA doesn't know your local bakery's sourdough, you can teach the app yourself.

**What keeps it from 9**

- Coverage is 43%, not 90 — the majority of the pantry still contributes nothing to nutrition charts. The next lever is matching the top unmatched items *by spend* (the X-Ray queue surfaces exactly this).
- `custom_nutrients` has zero rows in the live DB so far — the feature exists but hasn't been exercised; the top-20-items-by-spend hand-fix from the original plan is still worth doing.
- **Single deep source.** USDA FDC is the only source with real depth today (OpenFoodFacts is wired in — `off_code`, `external_product` service — but covers just 33 items, ~2%). The enrichment layer is deliberately pluggable, and this is a **good extension point for contributors**: deepening the OpenFoodFacts integration (barcode lookup, Nutri-Score, international products), or adding other open datasets (e.g., regional food-composition databases), would raise coverage without touching the analytics layer. The service boundary (`fdc_service` / `external_product` → `nutrition_utils.merge_nutrients`) is where a new source plugs in.

---

## Remediation Plan — Status

### Phase 1 — Feed the nutrition pipeline ✅ shipped

1. ✅ Full FDC sweep — nutrient coverage 8% → 43% of items.
2. ✅ Package-size fallback for discrete items in `nutrition_utils`.
3. ✅ Coverage surfaced honestly — spend-weighted badge on trends, linked to the X-Ray match queue.
4. ✅ Manual override UI wired end-to-end (`custom_nutrients` editable from item insights). *Still to exploit: hand-fix the top-20 items by spend.*
5. ✅ Reframed as purchase-profile, not intake.

### Phase 2 — Structural engineering debt ✅ shipped

6. ✅ Big four modules split (`main.py` → 188 lines; pages, fragments, review, nutrition-trends extracted).
7. ⚠️ Sync/async: README claim corrected; blocking HTTP remains in background-task-only services (acceptable, documented).
8. ✅ Alembic is the sole schema authority (`upgrade head` at startup).
9. ✅ Repo hygiene: DB/logs/scratch ignored, tree clean, history squashed.
10. ✅ `SAWarning` fixed; rate limiter bounded with idle-IP sweep.

### Phase 3 — AI compounding loop ✅ shipped

11. ✅ Dynamic few-shot from corrections, scoped per store.
12. ✅ Structured outputs on the Gemini path (Pydantic response schema + fail-soft fallback).
13. ✅ Eval harness (`scripts/ocr_eval.py`) scoring item-count, totals, and per-line accuracy.

### Phase 4 — Design & utility polish ✅ shipped

14. ✅ Precompiled Tailwind (standalone CLI, no Node); CDN hosts dropped from CSP. `'unsafe-eval'` retained deliberately for Alpine — documented trade-off.
15. ✅ Category taxonomy collapsed 163 → 13.
16. ✅ Folder-watch ingester (`data/inbox`), plus text-paste ingestion as a second friction-killer. PWA/barcode capture remains open.

### What's next (new backlog, in rough priority order)

- **Nutrition coverage past 50%**: match the top unmatched items by spend via the X-Ray queue; hand-enter the top-20; deepen OpenFoodFacts (see extension note above).
- **Enrichment scalability**: replace the load-all-items fuzzy scan with an indexed candidate lookup before the pantry hits five digits.
- **Template decomposition**: break the heaviest inline-Alpine pages into components.
- **In-store capture**: PWA + camera/barcode remains the largest remaining utility gap.

---

*Bottom line: a week ago this was "a strong product with one under-fed subsystem and some structural debt." The subsystem got fed (8% → 43%), the debt got paid, and the AI pipeline now compounds — corrections persist, outputs are schema-bound, and changes are measurable. What remains is growth work (coverage, capture paths, household support), not repair work.*
