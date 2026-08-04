# Grocery Tracker Exclusion Logic

This document defines the various layers of filtering, ignoring, and excluding data within the Grocery Tracker application. These mechanisms prevent data noise from affecting analytics and streamline the item management workflow.

## 1. Duplicate Match Exclusions (Ignored Suggestions)

*   **Purpose**: Prevents the system from repeatedly suggesting the same incorrect merge for two distinct items.
*   **Mechanism**: `ItemMatchIgnore` table in the database.
*   **View Excluded From**: **Items > Find Duplicates** tab.
*   **Action**: When a user clicks "Dismiss" on a duplicate suggestion, a record is created in `item_match_ignores` for that pair of IDs.
*   **Restoration**: Ignored pairs can be viewed and restored in the **Items > Dismissed** tab.

## 2. Ingestion & OCR Filters (Junk Removal)

*   **Purpose**: Strips marketing fluff and transaction metadata from item names during the initial PDF/Image parsing.
*   **Mechanism**: Hardcoded `skip_keywords` and `junk_filters` (RegEx) in `backend/app/services/pdf_parser.py`.
*   **View Excluded From**: **All views** (Receipts, Items, Dashboard). These strings are removed before the data is saved to the database.

### Skip Keywords (Metadata)
The following lines are ignored entirely during parsing. These are the **fallback defaults** — the live list is loaded from `data/ocr_filters.json` (editable without restarting the app):
- `Purchased at`, `Order Summary`, `Order Details`
- `Item(s) Subtotal`, `Shipping`, `Total before tax`
- `Estimated tax`, `Grand Total`, `Order placed`, `Order #`
- `PAGE`, `PICKUP AT`, `Payment method`

### Junk Filters (Marketing Strings)
The following strings are stripped from item names. These are the **fallback defaults** — the live list is in `data/ocr_filters.json`:
- `, Non-GMO`, `, Gluten-Free`
- `, with Immune Support`, `, Award Winning`

## 3. Analytics & Dashboard Exclusions

*   **Purpose**: Suppresses non-grocery costs (taxes, shipping, service fees) from spending charts and totals.
*   **Mechanism**: `_is_excluded()` in `backend/app/api/analytics.py`, driven by `ExclusionRule` table entries with `scope='analytics'`.
*   **Matching**: Case-insensitive substring against both **category names** and **item names**. For example, a pattern `crv` will hide items named "CRV 6PK UNDER 240Z AB" even if they are categorized as "Fees & Taxes" or "Other".
*   **View Excluded From**:
    - **Dashboard**: "Total Spent" summary card.
    - **Dashboard**: "Spend by Category" charts.
    - **Dashboard**: Category Drilldown modals.
    - **X-Ray**: All 5 visualizations (Volatility, Store DNA, Phantom Items, Rhythm, Complexity).
*   **Default patterns** (when no rules are configured): `excluded`, `other`, `taxes & fees`.

> [!TIP]
> To hide a specific item from your spending totals, add its name (or a substring of it) to Settings → Analytics Exclusions — e.g. adding `crv` will hide all CRV items.

---
*Last Updated: August 3, 2026*
