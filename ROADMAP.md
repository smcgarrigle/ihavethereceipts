# Grocery Price Tracker - Strategic Roadmap

---

## 🟡 Near-Term Backlog

### 1. Nutrition Catch-Up
Automated background enrichment that detects FDC coverage gaps and surfaces candidates for user review — turning the manual `scripts/backfill_nutrients.py` workflow into a self-service feature.

- [ ] **`NutritionEnricher` daemon**: Singleton background thread (same pattern as `BulkProcessor`). Searches FDC for uncovered items prioritized by spend; stores candidates in `nutrition_suggestions` for review.
- [ ] **Trigger logic**: Auto-fires after receipt saves when enrichable coverage drops below a configurable threshold (default 70%). Manual "Run Catch-Up" button in Settings.
- [ ] **Review page** (`/settings/nutrition-review`): Items sorted by spend impact with approve/reject/search actions. Batch approve for speed.
- [ ] **Persistent notification banner**: Shows pending suggestion count across all pages until reviewed or dismissed.
- [ ] **Settings card**: Coverage indicator, threshold slider, enable/disable toggle. Exclude Fees & Taxes / Household from the enrichable denominator.

### 2. Price History & Volatility
- [ ] **Retailer Overlays**: Overlay multiple stores on a single item's price history chart.
- [ ] **Volatility Alerts**: UI notifications for items with >15% price shifts in the last 30 days.
- [ ] **Advanced Spreadsheet Grid**: High-density thermal-coded grid for price history analysis.

### 3. AI & Data Enrichment
- [ ] **Barcode Scanning**: Mobile camera integration pulling product metadata from OpenFoodFacts.

### 4. Dynamic Trends & Dashboards
- [ ] **Interactive Chart Controllers**: Dropdown filters by date range, store, or category. Use `hx-push-url="true"` to keep state bookmarkable.
- [ ] **Low-Data "Bootstrap" Charts**: Visualizations useful with only 5–10 receipts.
- [ ] **Shopping Habits Gallery**: Recurring trend charts with improved signal/noise filtering.

### 5. Automation & Scalability
- [ ] **Household Support**: Individual accounts with shared or separate grocery databases.
- [ ] **Cross-Device Sync (Offline-First)**: PWA with IndexedDB for offline scanning; syncs back to server on reconnect.

### 6. UI/UX Refinements
- [ ] **Items Page Pagination**: `/items` renders all 1,493 items with no pagination (~80K DOM nodes). Prerequisite: extract `list_items` into a paginated Jinja fragment. Also unblocks column-reorder and the a11y axe suite.
- [ ] **Reorderable Item Columns**: Drag-to-reorder column headers (Category, qty, total spent, weight/vol, unit, $/unit) persisted in localStorage. Requires paginated fragment above. Full scope: `scratch/TODO_items_column_reorder.md`.
- [ ] **Mobile Slide-out Drawers**: HTMX-powered slide-up drawers for Item Insights on mobile, replacing full-page navigations.
- [ ] **PDF Viewer 'Esc' Key Fix**: Native `<embed>` swallows the 'Esc' key when focused, preventing modal close. Option A (lightweight): auto-focus the "Close" button on open. Option B (heavy): migrate to PDF.js.

### 7. Custom Category Lenses
Let users create personally meaningful categories (e.g. "Protein-Maxxing") that cut across canonical lines. The data model and charts already support it — the work is UX only.

- [ ] **Per-category item list with checkboxes** + bulk "move to…" + "create category from selection".
- [ ] **Re-categorization warning**: Warn (don't block) that moving items rewrites all historical chart data for those items.
- [ ] **Prerequisite**: Retire or redirect the orphaned `/categories` page left unlinked by the nav redesign.
- [ ] **Later**: Feedback-loop taxonomy learning so new item variants land in user lenses automatically.

### 8. AI Agent Assistant shopping
- [ ] **Agentic Shopping**: Hand off the prediction list to an agent that shops online for you and builds cart based around opitmal pricing and the urgency of restock
- [ ] **currently prohibited by TOS**

---

## 🏛️ Completed Milestones Archive

<details>
<summary><b>Accessibility & WCAG (Jul 2026)</b></summary>

- **Accessibility Sweep**: axe-core + Playwright smoke suite over 9 pages (`uv run pytest -m e2e`). All `<canvas>` charts carry `role="img"` + `aria-label`. All form fields and icon-only buttons have accessible names. Items-page tabs get full `role=tablist/tab/tabpanel` + roving tabindex. Accordions and disclosure buttons get `aria-expanded`/`aria-controls`. Toggle-mode buttons get `aria-pressed`. Every modal traps Tab and returns focus to its trigger. All `<img>` elements have alt text. Color-only signal in the category spend-stack widget fixed with `aria-label` + keyboard support. Fixed two pre-existing bugs surfaced by the audit.
- **WCAG AA Contrast**: All four themes satisfy SC 1.4.3 (≥4.5:1 text) and SC 1.4.11 (≥3:1 input borders). New `--text-subtle`, `--text-code`, `--border-input` tokens. Guarded by `scripts/check_contrast.py`. *(Chart-fill label contrast deferred.)*

</details>

<details>
<summary><b>OCR & AI Quality (Jul 2026)</b></summary>

- **OCR Feedback Loop**: Human review corrections persisted to `ocr_corrections` table and injected as few-shot examples into future OCR prompts. Cache keyed on image + prompt.
- **Gemini Structured Outputs**: API path passes `_ReceiptSchema`, guaranteeing valid JSON. `json-repair` retained as local-model fallback.
- **OCR Eval Harness**: `scripts/ocr_eval.py` scores extraction accuracy. Baseline: 91% item recall, 100% precision, 47% price accuracy.
- **Store-Scoped Matching**: `item_matcher.py` ranks items previously purchased at the current store ahead of near-tied text matches (raw-score gap ≤10). Never lowers the match threshold.
- **Full USDA FDC Sweep**: Checkpointed backfill matched 498 items via FDC + 24 via OpenFoodFacts. Nutrient coverage rose from 8% to 49% of items.

</details>

<details>
<summary><b>Taxonomy & Data Integrity (Jun–Jul 2026)</b></summary>

- **Category Taxonomy Collapse**: 92 fragment categories (338 items) merged into a strict 13-category canonical set. `category_mapper` interceptor prevents re-fragmentation.
- **Nutrition Pipeline Phase 1**: Full-payload FDC enrichment, package-size fallback, manual overrides, coverage badges on nutrition charts.
- **Structural Refactor**: `main.py` reduced to ~175 lines; page routes, analytics, and nutrition trends extracted into per-domain routers. Alembic is now the single schema authority.

</details>

<details>
<summary><b>Infrastructure & UI (Jun 2026)</b></summary>

- **Precompiled Tailwind + CSP**: Browser Play CDN replaced by a static build (`scripts/build_css.sh`); Inter vendored; zero external requests.
- **Local Folder-Watch Ingestion**: Drop PDFs/images into `data/inbox` for auto-ingest through the OCR + review pipeline. (`FOLDER_WATCH=0` to disable.)
- **Multi-Theme Engine**: CSS variable-based theming with Alpine.js. Light, Dark, Forest, Sunset themes across all 13 templates.
- **Shopping List Optimizer**: Store-grouped urgent restock view at `/restock`.
- **Reorder Prediction Engine**: Purchase cadence analysis with predicted exhaustion dates and urgency tiers. TTL-cached `/api/predictions/` endpoint suite.
- **Open Produce Mode**: Ultra-fast manual entry for loose/bulk items.
- **Export Data Engine**: One-click CSV/Excel export of full purchase history.
- **AI-Powered Size Extraction**: Automated unit pricing from OCR item names.
- **Bulk Pricing UI**: Hybrid ⚖️/🏷️ toggle for Per-Item vs Per-Weight pricing in the review screen.
- **PDF Receipt Viewer Fix**: `X-Frame-Options` set to `SAMEORIGIN` for in-app PDF embedding.
- **SSE Radar Pulse**: Live scanning feedback on the thermal view.

</details>

<details>
<summary><b>Phase 15: Data Quality Cleanup (Jun 2026)</b></summary>

- Deep audit of 158 PDF-imported receipts (Amazon/iHerb). 1,318 items patched for size/unit/price. 127 dates recovered. 86 junk items removed. Store names normalized. 33 receipts deleted. 5 reusable maintenance scripts added to `backend/scripts/`.

</details>

<details>
<summary><b>Phases 11–13: Performance & Local AI (Late May–Jun 2026)</b></summary>

- **Phase 13**: Bulk Receipt Loader & Background Processor.
- **Phase 12**: Weight Extraction Automation & Categorization History.
- **Phase 11**: Local OCR Support (Ollama, Granite 3.3 Vision).

</details>

<details>
<summary><b>Phases 6–10: Analytics & UX (May 2026)</b></summary>

- **Phase 10**: Duplicate Dismissal & Store History Modals.
- **Phase 9**: Mobile Responsiveness & Hamburger Menus.
- **Phase 8**: Bi-directional Price Calculation Logic.
- **Phase 7**: Dark Mode & Loading States.
- **Phase 6**: Initial Price Comparison Pills & Category Charts.

</details>

<details>
<summary><b>Phases 1–5: Foundation (Apr–May 2026)</b></summary>

- **Phase 5**: Duplicate Detection & Merging.
- **Phase 4**: Fuzzy Matching & AI Categorization.
- **Phase 3**: Receipt Review UI (Manual Adjustment).
- **Phase 2**: OCR Pipeline (Gemini 1.5).
- **Phase 1**: Core Infrastructure (FastAPI, SQLite, SQLAlchemy).

</details>

---
*Last Updated: August 3, 2026*
