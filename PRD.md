# Product Requirements Document (PRD) - IHaveTheReceipts
For AI agent behavior and coding style, see [GEMINI.md](GEMINI.md).

## 1. Problem Statement
Grocery prices are volatile and confusing. Consumers struggle to:
- Track how much they are spending on specific categories (e.g., Produce vs. Snacks).
- Remember "good" prices for items they buy regularly.
- Compare prices across different stores (e.g., Costco vs. Trader Joe's).
- Maintain a digital history of their paper receipts with minimal manual entry.

## 2. Product Goals
1.  **Zero-Friction Entry**: Make receipt capture as effortless as possible via AI OCR.
2.  **Data Precision**: Ensure extracted data is accurate, normalized, and granular (unit prices, discounts).
3.  **Actionable Intelligence**: Provide insights that help users save money

## 3. User Stories

### Core Experience
- **Capture**: As a user, I want to take a photo of my receipt so that it is digitally stored and analyzed.
- **Review**: As a user, I want to quickly verify the AI's work and fix any mistakes before saving.
- **Search**: As a user, I want to search for "eggs" and see every time I bought them, where, and for how much.

### Analytics & Value
- **Trends**: As a user, I want to see if the price of eggs is going up over time.
- **Comparison**: As a user, I want to know if Costco's bulk price is actually cheaper per unit than the local grocery store.
- **Budgeting**: As a user, I want to see my monthly spend breakdown by category.

### Data Management
- **Cleanup**: As a user, I want to merge "Banana" and "Bananas (Organic)" so my history is consistent.
- **Organization**: As a user, I want my items to be automatically categorized (e.g., "Dairy", "Produce") without me typing anything.

## 4. Functional Requirements

### 4.1. Receipt Processing
- **Input**: Support JPG, PNG, and multi-page PDF uploads.
- **OCR Engine**: Use Google Gemini Vision API for high-accuracy text extraction.
- **Parsing**:
    - Extract Store Name, Date, Total Amount.
    - Extract Line Items: Name, Quantity, Price.
    - Identify Discounts and apply them to the correct lines.
    - Identify Fees (CRV, Tax) and associate them with items or the subtotal.
- **Normalization**: Auto-correct store names (e.g., "TRADER JOE'S #123" -> "Trader Joe's").

### 4.2. Receipt Review Interface
- **Bi-directional Calculation**: Editing Unit Price updates Total; editing Total updates Unit Price.
- **Validation**: Warn on missing names, negative prices (unless discounts), or logic errors.
- **Original View**: Side-by-side view of the original receipt image/PDF during review.

### 4.3. Item Management system
- **Canonicalization**: Items purchased across different receipts link to a single "Item" record.
- **Fuzzy Matching**: Automated detection of similar names (e.g., "Avocado Lrg" vs "Avocado Large").
- **Smart Merge**: Tools to merge duplicate items while preserving historical receipt links.
- **Auto-Categorization**: AI-driven categorization for new items.

### 4.4. Analytics Dashboard
- **Recent Receipts**: Reverse-chronological feed of shopping trips.
- **Top Metrics**: Total spent this month, top categories, top expensive items.
- **Price History**: Line/Scatter charts showing unit price changes over time.
- **Store Comparison**: "Best Price" indicators for items available at multiple stores.

## 5. Non-Functional Requirements
- **Performance**: Receipt upload to review screen in < 10 seconds.
- **Responsiveness**: Fully functional on mobile web (iOS/Android) via standard browser.
- **Privacy**: All receipt images and data stored locally or in self-hosted infrastructure.
- **Reliability**: Graceful handling of API failures (e.g., Gemini quota exceeded).
- **Usability**: Dark mode support for low-light usage.

## 6. Shipped Post-MVP Enhancements
- **USDA FDC Full Sweep & Catch-Up Daemon**: Automated background enrichment searching FoodData Central by spend impact with human review UI (`/settings/nutrition-review`).
- **Volatility Alerts & Matrix**: Dynamic tracking for items with >15% price shifts in 30 days and thermal price history grid.
- **TruePriceMemory Browser Extension**: Read-only Manifest V3 Chrome and Firefox WebExtension surfacing local price history and deal verdicts on Amazon Fresh and Safeway.
- **Data Table Modernization**: Server-side pagination and broker-style drag-to-reorder columns persisted in `localStorage`.
- **OCR Feedback Loop**: Few-shot correction injection and permanent per-store printed name memory (`store_item_aliases`).

## 7. Future Scope
- **Barcode Scanning**: Mobile camera integration pulling GTIN product metadata from OpenFoodFacts.
- **Interactive Chart Controllers**: Filter dropdowns across trends pages maintaining bookmarkable state via `hx-push-url`.
- **Custom Category Lenses**: User-defined categories (e.g. "Protein-Maxxing") cutting across canonical boundaries.
- **Mobile Slide-out Drawers**: HTMX-powered slide-up bottom sheets for Item Insights on phones.
- **Multi-User Household Support**: Separate or shared grocery accounts.
- **Offline-First PWA**: Progressive Web App with IndexedDB local caching and server synchronization.
