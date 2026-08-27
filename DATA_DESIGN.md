# Database Design - IHaveTheReceipts

This document outlines the database schema, relationships, and field definitions used in the IHaveTheReceipts application. The system uses **SQLite** for single-user portability and zero-config operation.

## Entity Relationship Diagram (ERD)

```mermaid
erDiagram
    stores ||--o{ receipts : "hosts"
    stores ||--o{ ocr_corrections : "scoped to"
    categories ||--o{ items : "categorizes"
    receipts ||--o{ receipt_items : "contains"
    receipts ||--o{ ocr_corrections : "captures"
    items ||--o{ receipt_items : "referenced in"
    items ||--o{ item_match_ignores : "item1"
    items ||--o{ item_match_ignores : "item2"
    items ||--o{ merge_logs : "target"

    stores {
        int id PK
        string name UK "Unique store name"
        string address "Optional"
    }

    categories {
        int id PK
        string name UK "Category name (Meat, Dairy, etc.)"
    }

    items {
        int id PK
        string name "Original name"
        string normalized_name IX "Normalized for matching"
        int category_id FK
        int fdc_id "USDA FoodData Central ID"
        bool fdc_override "True = user manually set FDC match"
        string gtin "Barcode (OpenFoodFacts)"
        string off_code "OpenFoodFacts product code"
        string image_url "Remote product image"
        string image_path "Local product image"
        string nutriscore "Nutri-Score grade (A-E)"
        string ingredients "Ingredients text"
        json nutrients "USDA/FDC nutrition payload"
        json custom_nutrients "User-entered nutrition overrides"
        string nutrition_source "auto | manual | fdc | off"
        datetime created_at
    }

    receipts {
        int id PK
        int store_id FK
        string image_path "Path to uploaded file"
        float total_amount
        datetime purchase_date
        datetime created_at
        float discount_amount
        string discount_type
        string discount_description
        text notes
        string status "pending, processing, completed, failed"
        text error_message
        text ocr_data "JSON: full raw AI extraction"
        string order_number UK "Unique ID from digital PDFs"
    }

    receipt_items {
        int id PK
        int receipt_id FK
        int item_id FK
        float quantity
        float price "Per-quantity price — spend is price * quantity"
        text notes "JSON: Discounts/Fees breakdown"
        float unit_price "Calculated effective price"
        string unit_type "oz, lb, unit, etc."
        float weight "Optional for weight-based items"
        float original_unit_price "Price before discounts"
        float total_discount "Savings for this line"
    }

    ocr_corrections {
        int id PK
        int receipt_id FK
        int store_id FK "Nullable — for store-scoped few-shot injection"
        string field "name | price | quantity | store_name | total_amount | item_missed | item_hallucinated"
        text item_context "Item name context for field-level fixes"
        text ai_value "What the AI originally extracted"
        text approved_value "What the user corrected it to"
        datetime created_at
    }

    exclusion_rules {
        int id PK
        string scope "analytics | predictions"
        string pattern "Category name substring to match"
        string reason "Optional user-facing note"
        datetime created_at
    }

    item_match_ignores {
        int id PK
        int item_id_1 FK
        int item_id_2 FK
        datetime created_at
    }

    merge_logs {
        int id PK
        int target_item_id FK
        string source_item_name
        int source_item_category_id
        text receipt_item_ids "JSON list of IDs moved"
        datetime merged_at
    }
```

---

## Table Definitions

### 1. `stores`
Stores represent the locations where purchases were made. Store names are normalized during ingestion using `app.services.store_utils.normalize_store_name` to avoid duplicates (e.g., "SAFEWAY #1234" → "Safeway").

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | Integer | Primary Key |
| `name` | String | Unique store name, indexed for fast lookups. |
| `address` | String | Optional physical address. |

### 2. `categories`
Top-level classification for grocery items. The application enforces a strict 13-category canonical taxonomy via the `category_mapper` interceptor, which prevents new external names (from USDA/OpenFoodFacts) from fragmenting the set. User-created categories pass through untouched.

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | Integer | Primary Key |
| `name` | String | Unique category name. |

### 3. `items`
Unique product definitions. Every receipt line item is mapped to a record here using `normalized_name`. The `items` table also holds the full nutrition enrichment payload from USDA FoodData Central and OpenFoodFacts.

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | Integer | Primary Key |
| `name` | String | The first-ever name seen for this item. |
| `normalized_name` | String | Cleaned, lowercase version used as a matching key. |
| `category_id` | Integer | ForeignKey to `categories`. |
| `fdc_id` | Integer | USDA FoodData Central food ID (nullable). |
| `fdc_override` | Boolean | `True` if the user manually selected the FDC match. |
| `gtin` | String | Barcode/GTIN from OpenFoodFacts (nullable). |
| `off_code` | String | OpenFoodFacts product code (nullable). |
| `image_url` | String | Remote product image URL (nullable). |
| `image_path` | String | Local cached product image path (nullable). |
| `nutriscore` | String | Nutri-Score grade A–E (nullable). |
| `ingredients` | String | Ingredients text (nullable). |
| `nutrients` | JSON | Full nutrition payload from FDC/OpenFoodFacts. |
| `custom_nutrients` | JSON | User-entered nutrition values; merged over `nutrients` at read time via `effective_nutrients`. |
| `nutrition_source` | String | Origin of nutrition data: `auto`, `manual`, `fdc`, or `off`. |
| `created_at` | DateTime | Timestamp of first discovery. |

### 4. `receipts`
Metadata and headers for uploaded or manually created receipts.

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | Integer | Primary Key |
| `store_id` | Integer | ForeignKey to `stores`. |
| `image_path` | String | URL or file path to the original receipt image/PDF. |
| `total_amount` | Float | The grand total paid. |
| `purchase_date` | DateTime | The date printed on the receipt. |
| `status` | String | State of processing: `pending`, `processing`, `completed`, `failed`. |
| `order_number` | String | Unique identifier (Order ID) extracted from digital receipts for de-duplication. |
| `ocr_data` | Text | **JSON Blob**: Full raw AI extraction, retained for re-processing with different models. |

### 5. `receipt_items`
Individual line items extracted from a receipt. Maps a `receipt` to an `item`.

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | Integer | Primary Key |
| `receipt_id` | Integer | ForeignKey to `receipts`. |
| `item_id` | Integer | ForeignKey to `items`. |
| `quantity` | Float | Number of units purchased. |
| `price` | Float | **Per-quantity price**, after fees/discounts. The line total is `price × quantity` — the app reads spend that way everywhere (`analytics.py`, `receipts.py`, `receipts_review.py`), so storing a line total here silently double-counts every row with `quantity > 1`. Weight-priced lines carry `quantity = 1`, so for those `price` *is* the line total. |
| `unit_price` | Float | The **true price per unit of measure** ($ / lb or $ / oz) — used for cross-store comparison, not for computing the line total. Differs from `price` whenever `unit_type` is a weight. |
| `unit_type` | String | The unit of measure (lb, oz, each, etc.). |
| `weight` | Float | Total weight for weight-based items (nullable). |
| `original_unit_price` | Float | Price before any line-item discount was applied. |
| `total_discount` | Float | Total savings recorded on this line. |
| `notes` | Text | **JSON Blob**: Breakdown of specific discounts or fees applied to this item. |

### 6. `ocr_corrections`
Captures every human fix made in the receipt review sandbox. These records are injected as few-shot examples into future OCR prompts (store-scoped on reprocess, global on first pass), forming the self-improving feedback loop.

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | Integer | Primary Key |
| `receipt_id` | Integer | ForeignKey to `receipts`. |
| `store_id` | Integer | ForeignKey to `stores` (nullable — used for store-scoped injection). |
| `field` | String | What was corrected: `name`, `price`, `quantity`, `store_name`, `total_amount`, `item_missed`, `item_hallucinated`. |
| `item_context` | Text | The item name associated with a field-level fix. |
| `ai_value` | Text | What the AI originally extracted. |
| `approved_value` | Text | What the user corrected it to. |
| `created_at` | DateTime | Timestamp of the correction. |

### 7. `exclusion_rules`
Category-level exclusions that hide specific categories from analytics charts and/or the prediction/restock engine. Managed from the Settings page.

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | Integer | Primary Key |
| `scope` | String | `analytics` (hides from dashboard/charts) or `predictions` (hides from restock engine). |
| `pattern` | String | Category name substring to match. |
| `reason` | String | Optional user-facing explanation (nullable). |
| `created_at` | DateTime | Timestamp. |

### 8. `item_match_ignores`
Stores dismissed duplicate suggestions. Prevents the matching engine from re-suggesting a specific pair of items that the user has already declared are different.

### 9. `merge_logs`
Audit trail for item merges. If "Milk A" is merged into "Milk B", this table records what happened for potential audit or reversal.

---

## Notable Architecture Details

### JSON in SQLite
Several fields (`ocr_data`, `receipt_items.notes`, `merge_logs.receipt_item_ids`, `items.nutrients`, `items.custom_nutrients`) use `Text` or `JSON` column types to store structured data. In the backend, these are parsed into Pydantic models or Python dictionaries at read time.

### Bi-directional Pricing

The invariant, for anything that writes `receipt_items`:

```
line total  =  price × quantity
```

`price` is per-quantity, never the line total. Every spend figure in the app is
derived by multiplying (`analytics.py` ×4, `receipts.py`, `receipts_review.py`),
and the review page's total-mismatch warning compares that sum against
`receipts.total_amount`. An importer or seed script that puts a line total in
`price` inflates all spend and trips that warning on most receipts — this has
happened once already, in `seed_demo.py`, and is now guarded by
`tests/test_seed_demo_totals.py`.

Weight-priced lines carry `quantity = 1`, so `price` equals the line total for
those, and `unit_price` holds the per-lb figure.

When units (oz, lb) are present the app also calculates density pricing for
cross-store comparison (e.g. a 12 oz juice at Store A vs a 1 L juice at Store B).
**Note:** Always use `(Price × Qty) / TotalWeight` for unit price — not
`Price / (Weight × Qty)`, which causes $0.00 rounding errors.

### Nutrition Merge Strategy
`items.custom_nutrients` overlays `items.nutrients` at read time via the `effective_nutrients` property. This means user corrections (manual entry from the Item Insights page) always take precedence over automatically enriched FDC data without destroying the original payload.

### De-duplication Strategy
1. **Order IDs**: Digital receipts use the `order_number` field (unique constraint) to prevent duplicate uploads.
2. **Store Normalization**: `app.services.store_utils.normalize_store_name` maps receipt text variants (e.g., "SAFEWAY #1234") to a single canonical store record.
3. **Item Matching**: `app.services.item_matcher` uses `rapidfuzz` for fuzzy string matching, with store-scoped context boosting to prefer items previously purchased at the current store.
