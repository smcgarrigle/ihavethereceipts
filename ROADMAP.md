# Grocery Price Tracker - Strategic Roadmap

This document outlines the development trajectory of the Grocery Price Tracker, from core infrastructure to advanced AI-driven analytics and visualization.

---

## 🟢 Current Status: Phase 1 Strategic Vision Complete
All three Strategic Vision phases have been delivered as of May 2026. The application is now in active use with a full prediction engine, multi-theme UI, and store-optimized shopping lists.

### [Phase 14] Advanced Entry & Visuals ✅ (April 2026)
- **Bulk Pricing UI (⚖️/🏷️)**: Hybrid toggle for Per-Item vs Per-Weight pricing in the review screen.
- **SSE Radar Pulse**: Live scanning feedback on the thermal view.
- **Export & Entry Engine**: CSV/Excel Export Engine and Quick Produce Entry.

### [Phase 16] Strategic Vision — Phase 1 ✅ (May 2026)
- **Multi-Theme Engine**: CSS variable-based theming with Alpine.js. Supports Light, Dark, Forest, and Sunset themes across all pages (329 class replacements across 13 templates).
- **Shopping List Optimizer**: Store-grouped urgent restock view at `/restock` — surfaces the best store per item based on historical price data.
- **Reorder Prediction Engine**: Purchase cadence analysis with predicted exhaustion dates, urgency tiers, and a TTL-cached `/api/predictions/` endpoint suite.
- **Data Normalization**: Multipack price correction (Non-Alcoholic Beer 6/12-packs), item name cleanup scripts, and Amazon Fresh boilerplate removal.
- **PDF Receipt Viewer Fix**: `X-Frame-Options` updated to `SAMEORIGIN` to enable in-app PDF embedding.

---

## 🟢 Recently Completed (Q3 2026)
- [x] **WCAG AA Contrast Compliance (July 2026)**: All four themes (Light/Dark/Forest/Sunset) plus the marketing site now satisfy WCAG 2.1 SC 1.4.3 *Contrast (Minimum)* — every text token ≥ 4.5:1 on its surfaces — and SC 1.4.11 *Non-text Contrast* for form input borders (≥ 3:1, Option A: card borders remain decorative and rely on shadows). Changes: `--text-subtle` raised in light (2.4→4.6:1) and dark (3.0→4.8:1); new `--text-code` token for inline code/debug badges in dark (4.1→6.2:1); `--border-input` raised in all themes (3.1–3.3:1); button hover states no longer dip below AA (`hover:bg-blue-500` → `700`). Guarded by `scripts/check_contrast.py`, which parses the tokens from CSS and fails on any violation. *Deferred: chart-fill label contrast and SC 1.4.1 Use of Color (color-only signaling).*
- [x] **OCR Feedback Loop (Self-Improving Extraction)**: Human corrections from the review sandbox are persisted (`ocr_corrections` table) and injected into future OCR prompts as few-shot examples. The OCR cache is keyed on image + prompt, so learned corrections invalidate stale results on reprocess.
- [x] **Gemini Structured Outputs**: The API path now passes a response schema (`_ReceiptSchema`), contractually guaranteeing valid JSON; `json-repair` remains as the local-model fallback. Fails soft to prompt-only JSON if a model rejects the schema.
- [x] **OCR Eval Harness**: `scripts/ocr_eval.py` scores extraction accuracy against human-approved receipts — `--stored` for a zero-cost baseline, `--live` to measure prompt/model changes. Baseline: 91% item recall, 100% precision, 47% price accuracy (the current improvement target).
- [x] **Nutrition Pipeline Phase 1**: Full-payload FDC enrichment, package-size fallback for discrete items, working manual overrides, and honest coverage badges on all nutrition charts.
- [x] **Structural Refactor**: main.py reduced to pure app wiring (~175 lines); page routes, analytics fragments, and nutrition trends extracted into per-domain routers. Alembic is now the single schema authority (migrations run at startup).
- [x] **Precompiled Tailwind + Self-Contained CSP**: browser Play runtime replaced by a static build (`scripts/build_css.sh`); Inter vendored; zero external requests.
- [x] **Category Taxonomy Collapse**: 92 fragment categories (338 items) merged into a strict 13-category canonical set; the interceptor in `category_mapper` prevents re-fragmentation.
- [x] **Local Folder Watch**: drop PDFs/images into `data/inbox` and they auto-ingest through the normal OCR + review pipeline (`FOLDER_WATCH=0` to disable).

## 🟢 Recently Completed (Q2 2026)
- [x] **Open Produce Mode**: A dedicated, ultra-fast manual entry system for loose/bulk items.
- [x] **Export Data Engine**: One-click export of entire purchase history to CSV/Excel.
- [x] **AI-Powered Size Extraction**: Fully automated unit pricing from OCR item names.
- [x] **Shopping List Optimizer**: Store-grouped urgent restock view.
- [x] **Multi-Theme Engine**: CSS variable refactor supporting Light, Dark, Forest, and Sunset themes.
- [x] **Purchase Cadence Engine**: Computes average purchase intervals and exhaustion dates.
- [x] **Agent-Friendly API Endpoints**: `/api/predictions/` endpoints ready for AI agents.

---

## 🟡 Near-Term Backlog & Strategic Roadmap

### 1. Taxonomy Cleanup & Category Merging ✅ (July 2026)
- [x] **Taxonomy Mapping Engine**: Strict 13-category canonical set defined.
- [x] **The Interceptor**: `category_mapper` funnels chaotic external categories (USDA/OpenFoodFacts) into the master taxonomy and prevents re-fragmentation.
- [x] **Database Migration**: Fragmented categories collapsed into the clean taxonomy (see "Category Taxonomy Collapse" above).

### 2. Price History & Volatility
- [ ] **Retailer Overlays**: Overlay multiple stores on a single item's price history chart to compare pricing.
- [ ] **Volatility Alerts**: Automated UI notifications flagging items with >15% price shifts in the last 30 days.
- [ ] **Advanced Spreadsheet Grid**: High-density, thermal-coded grid for price history analysis.

### 3. AI & Data Enrichment
- [x] **Dynamic AI Few-Shot Learning** ✅ (July 2026): Every review-sandbox save is diffed against the AI's original extraction; corrections are stored in `ocr_corrections` and injected into the OCR prompt (store-scoped on reprocess, global on first pass). See "OCR Feedback Loop" below.
- [x] **Full USDA FDC Sweep** ✅ (July 2026): Checkpointed backfill (`scripts/backfill_nutrients.py`) matched 498 items via FDC + 24 via OpenFoodFacts — nutrient coverage rose from 8% to 49% of items (45.9% of spend).
- [ ] **Barcode Scanning Support**: Mobile camera integration to pull global product metadata from OpenFoodFacts.

### 4. Dynamic Trends & Dashboards
- [ ] **Interactive Chart Controllers**: Dropdown menus to dynamically filter charts by date ranges, stores, or categories. Must use `hx-push-url="true"` to ensure URL query parameter state remains bookmarkable and shareable.
- [ ] **Low-Data "Bootstrap" Charts**: Visualizations designed to deliver insights with only 5–10 receipts.
- [ ] **Shopping Habits Gallery**: Recurring trend charts with improved signal/noise filtering.

### 5. Automation & Scalability
- [x] **Local Folder-Watch Ingestion** ✅ (July 2026): Drop PDFs/images into `data/inbox` and they auto-ingest through the normal OCR + review pipeline (`FOLDER_WATCH=0` to disable).
- [ ] **Household Support**: Individual accounts with shared or separate grocery databases.
- [ ] **Cross-Device Sync (Offline-First)**: Robust synchronization across mobile and desktop clients. Architect as a Progressive Web App (PWA) using IndexedDB to allow scanning and viewing in low-service grocery stores, syncing back to the server later.

### 6. UI/UX Refinements (Post-Launch)
- [ ] **Reorderable Item Columns (Broker-Style)**: Table view for the Items page with drag-to-reorder column headers (Category, qty, total spent, weight/vol, unit, $/unit), persisted in localStorage — plus show/hide toggles and click-to-sort. Prerequisite: extract the `list_items` f-string HTML into a Jinja fragment. Full scope: `scratch/TODO_items_column_reorder.md` (est. 1.5–2 days).
- [ ] **Mobile Slide-out Drawers**: Replace heavy full-page navigations for Item Insights on mobile with HTMX-powered slide-up drawers to preserve the user's context on the main Dashboard.
- [ ] **PDF Viewer 'Esc' Key Fix**: The native PDF `<embed>` swallows the 'Esc' key when focused, preventing the receipt review modal from closing.
  - *Option A (Lightweight)*: Auto-focus the modal's "Close" button upon opening so 'Esc' works immediately until the user clicks into the PDF.
  - *Option B (Heavy)*: Migrate from native `<embed>` to `PDF.js` to render PDFs as flat canvases that do not steal keyboard focus.

---

## 🏛️ Completed Milestones Archive

<details>
<summary><b>Phase 15: Data Quality Cleanup (May 2026)</b></summary>

- **Batch Import Audit**: Deep audit of 158 PDF-imported receipts (Amazon/iHerb).
- **1,318 items patched**: Size extraction (weight/unit/is_bulk) and unit_price recalculated from final_price.
- **127 dates recovered**: From PDF filename parsing and pdfplumber text extraction.
- **86 junk items removed**: Address strings and boilerplate scraped by PDF parser.
- **Store normalization**: `Iherb`/`IHerb` → `iHerb`, `Amazon` → `Amazon.com`.
- **33 receipts deleted**: 31 missing-PDF sources + 2 empty iHerb receipts. DB: 331 → 298.
- **5 reusable maintenance scripts** added to `backend/scripts/`.
- Full audit log: `DATA_CLEANUP_2026_05_02.md`.
</details>

<details>
<summary><b>Phases 11-13: Performance & Local AI (Feb-Apr 2026)</b></summary>

- **Phase 13**: Bulk Receipt Loader & Background Processor.
- **Phase 12**: Weight Extraction Automation & Categorization History.
- **Phase 11**: Local OCR Support (Ollama, Granite 3.3 Vision).
</details>

<details>
<summary><b>Phases 6-10: Analytics & UX (Dec 2025-Jan 2026)</b></summary>

- **Phase 10**: Duplicate Dismissal & Store History Modals.
- **Phase 9**: Mobile Responsiveness & Hamburger Menus.
- **Phase 8**: Bi-directional Price Calculation Logic.
- **Phase 7**: Dark Mode implementation & Loading States.
- **Phase 6**: Initial Price Comparison Pills & Category Charts.
</details>

<details>
<summary><b>Phases 1-5: Foundation (Sept-Nov 2025)</b></summary>

- **Phase 5**: Duplicate Detection & Merging logic.
- **Phase 4**: Fuzzy Matching & AI Categorization.
- **Phase 3**: Receipt Review UI (Manual Adjustment).
- **Phase 2**: OCR Pipeline (Gemini 1.5).
- **Phase 1**: Core Infrastructure (FastAPI, SQLite/PG, SQLAlchemy).
</details>

---
*Last Updated: July 17, 2026*

<!-- Search UX options considered (Option A implemented May 2026):
  Option B — Dedicated /search full-page (Enter key navigates to results page; table view with all purchase history)
  Option C — Command Palette Modal (Cmd+K overlay with fuzzy search, store chips, price preview; most premium feel)
  Both are viable follow-on upgrades to the current Option A enhanced dropdown. -->
