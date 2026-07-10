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
The following lines are ignored entirely during parsing:
- `Shipping`, `Estimated tax`, `Grand Total`, `Order Summary`
- `Order placed`, `Order Date`, `Order #`
- `PAGE`, `PICKUP AT`, `Payment method`

### Junk Filters (Marketing Strings)
The following strings are stripped from item names (primarily for Amazon/iHerb):
- `, with Immune Support`
- `, Non-GMO`, `, Gluten-Free`
- `, 7g Protein`, `, 27 Vitamins & Minerals for Kids`
- `, Award Winning`, `, Made with Real Fruit`

## 3. Analytics & Dashboard Exclusions

*   **Purpose**: Suppresses non-grocery costs (taxes, shipping, service fees) from spending charts and totals.
*   **Mechanism**: `exclude_list` in `backend/app/api/analytics.py`.
*   **View Excluded From**:
    - **Dashboard**: "Total Spent" summary card.
    - **Dashboard**: "Spend by Category" charts.
    - **Dashboard**: Category Drilldown modals.
*   **Logic**: Any item assigned to a category containing the following strings (case-insensitive) is hidden from analytics:
    - `excluded`
    - `other`
    - `taxes & fees`

> [!TIP]
> To hide a specific item from your spending totals, assign it to a category named **"Excluded - [Reason]"**.

---
*Last Updated: May 8, 2026*
