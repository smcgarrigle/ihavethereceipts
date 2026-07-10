# Database Design - Grocery Price Tracker

This document outlines the database schema, relationships, and field definitions used in the Grocery Price Tracker application. The system uses **SQLite** for single-user portability and zero-config operation.

## Entity Relationship Diagram (ERD)

```mermaid
erDiagram
    stores ||--o{ receipts : "hosts"
    categories ||--o{ items : "categorizes"
    receipts ||--o{ receipt_items : "contains"
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
        float price "Line item total"
        text notes "JSON: Discounts/Fees breakdown"
        float unit_price "Calculated effective price"
        string unit_type "oz, lb, unit, etc."
        float weight "Optional for weight-based items"
        float original_unit_price "Price before discounts"
        float total_discount "Savings for this line"
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
Stores represent the locations where purchases were made. Store names are normalized during ingestion to avoid duplicates (e.g., "WAL-MART" vs "Walmart").

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | Integer | Primary Key |
| `name` | String | Unique store name, indexed for fast lookups. |
| `address` | String | Optional physical address. |

### 2. `categories`
Top-level classification for grocery items (e.g., Produce, Dairy, Meat, Beverages).

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | Integer | Primary Key |
| `name` | String | Unique category name. |

### 3. `items`
Unique product definitions. The system attempts to map every receipt line item to a record in this table using `normalized_name`.

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | Integer | Primary Key |
| `name` | String | The first-ever name seen for this item. |
| `normalized_name` | String | A cleaned, lowercase version of the name used as a matching key. |
| `category_id` | Integer | ForeignKey to `categories`. |
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
| `ocr_data` | Text | **JSON Blob**: Stores the full raw response from Gemini/AI for re-processing. |

### 5. `receipt_items`
Individual line items extracted from a receipt. Maps a `receipt` to an `item`.

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | Integer | Primary Key |
| `receipt_id` | Integer | ForeignKey to `receipts`. |
| `item_id` | Integer | ForeignKey to `items`. |
| `quantity` | Float | Number of units purchased. |
| `price` | Float | The final amount paid for this line (including fees/discounts). |
| `unit_price` | Float | The **True Price per unit** ($ / lb or $ / unit). |
| `unit_type` | String | The unit of measure (lb, oz, each, etc.). |
| `notes` | Text | **JSON Blob**: Breakdown of specific discounts or fees applied to this item. |

### 6. `item_match_ignores`
Stores the "Ignored Suggestions" from the user. Prevents the AI from suggesting that two specific items should be merged if the user has already stated they are different.

### 7. `merge_logs`
Audit trail for item merges. If "Milk A" is merged into "Milk B", this table records what happened so it can be potentially reverted or audited.

---

## Notable Architecture Details

### JSON in SQLite
Several fields (`ocr_data`, `receipt_items.notes`, `merge_logs.receipt_item_ids`) use the `Text` type to store JSON strings. In the backend, these are parsed into Pydantic models or Python dictionaries.

### Bi-directional Pricing
The application enforces `Total = Qty * UnitPrice`. When units (oz, lb) are present, it further calculates the density pricing to allow comparisons (e.g., comparing a 12oz juice at Store A with a 1L juice at Store B).

### De-duplication Strategy
1. **Order IDs**: Digital receipts use the `order_number` field to prevent duplicate uploads.
2. **Store Normalization**: Uses `Levenshtein` distance to map varying receipt text (e.g., "SAFEWAY #1234") to a single "Safeway" store record.
