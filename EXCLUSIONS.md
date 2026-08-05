# Grocery Tracker Exclusion Logic

This document defines the various layers of filtering, ignoring, and excluding data within the Grocery Tracker application. These mechanisms prevent data noise from affecting analytics and streamline the item management workflow.

## 1. Duplicate Match Exclusions (Ignored Suggestions)

*   **Purpose**: Prevents the system from repeatedly suggesting the same incorrect merge for two distinct items.
*   **Mechanism**: `ItemMatchIgnore` table in the database.
*   **View Excluded From**: **Items > Find Duplicates** tab.
*   **Action**: When a user clicks "Dismiss" on a duplicate suggestion, a record is created in `item_match_ignores` for that pair of IDs.
*   **Restoration**: Ignored pairs can be viewed and restored in the **Items > Dismissed** tab.

---

## 2. Ingestion & OCR Filters (Junk Removal)

*   **Purpose**: Strips marketing fluff and transaction metadata from item names during the initial PDF/Image parsing.
*   **Mechanism**: `skip_keywords` and `junk_filters` in `backend/app/services/pdf_parser.py`, loaded at runtime from `data/ocr_filters.json`. The lists below are the hardcoded fallbacks used when the JSON file is missing.
*   **View Excluded From**: **All views** (Receipts, Items, Dashboard). These strings are removed before data is saved to the database.

### Skip Keywords (Metadata — entire line discarded)
`Purchased at` · `Order Summary` · `Order Details` · `Item(s) Subtotal` · `Shipping` · `Total before tax` · `Estimated tax` · `Grand Total` · `Order placed` · `Order #` · `PAGE` · `PICKUP AT` · `Payment method`

### Junk Filters (Marketing strings stripped from item names)
`, Non-GMO` · `, Gluten-Free` · `, with Immune Support` · `, Award Winning`

> [!TIP]
> Both lists are user-editable via `data/ocr_filters.json` without restarting the app. The fallback lists above are only used if the file is missing or unreadable.

---

## 3. Analytics & Dashboard Exclusions

Two distinct mechanisms apply here. It is important to understand which views are controlled by user-configured rules versus which are hardcoded.

### 3a. Dynamic Exclusion Rules (`ExclusionRule` table, `scope='analytics'`)

*   **Purpose**: User-configured patterns that suppress categories/items from specific analytics views.
*   **Mechanism**: `_is_excluded()` in `backend/app/api/analytics.py`, reading `ExclusionRule` rows with `scope='analytics'`. Managed from **Settings → Analytics Exclusions**.
*   **Matching**: Case-insensitive substring against both **category names** and **item names**. A pattern `crv` will hide items named "CRV 6PK UNDER 24OZ" even if their category is "Fees & Taxes" or "Other".
*   **Default patterns** (used when the table is empty): `excluded`, `other`, `taxes & fees`.
*   **Views affected by dynamic rules**:
    - **Dashboard**: BI Dashboard (30-day spend, macro breakdown).
    - **Dashboard**: Category-Store Stack widget.
    - **X-Ray**: All 5 visualizations — Price Volatility, Store DNA, Phantom Items, Shopping Rhythm, Receipt Complexity.

### 3b. Hardcoded Category Filter (`.notin_()` SQL)

*   **Purpose**: A fixed backstop that always removes known noise categories regardless of user rules.
*   **Mechanism**: SQLAlchemy `.filter(Category.name.notin_([...]))` embedded directly in query logic — **not** driven by `ExclusionRule`. Cannot be changed from Settings.
*   **Hardcoded exclusion list**: `Excluded`, `Other`, `Fees & Taxes`, `CRV (tax)`, `Non-Alcoholic Beer`.
*   **Views using this filter**:
    - **Dashboard**: "Total Spent" summary card (`summary_stats`).
    - **Dashboard**: "Spend by Category" chart (`spending_by_category`).

> [!NOTE]
> The two mechanisms are independent. Adding a custom pattern in Settings → Analytics Exclusions will affect the BI Dashboard and X-Ray views, but **not** the "Total Spent" card or "Spend by Category" chart — those use the hardcoded list only.

---

## 4. Prediction Engine Exclusions

*   **Purpose**: Suppresses categories from the restock/cadence engine so that non-consumable or noise categories don't generate restocking alerts.
*   **Mechanism**: `_get_excluded_categories()` in `backend/app/services/predictions.py`, reading `ExclusionRule` rows with `scope='predictions'`. Managed from **Settings → Prediction Exclusions**.
*   **Default patterns** (used when the table is empty): `Excluded`, `Other`, `Non-Alcoholic Beer`, `Fees & Taxes`, `CRV (tax)`.
*   **Views affected**: Restock alerts, cadence engine, shopping list suggestions.

---

*Last Updated: August 4, 2026*
