# TruePriceMemory Browser Extension

**TruePriceMemory** is a read-only Chrome and Firefox WebExtension (`extension/`) that connects to your local **IHaveTheReceipts** server (`http://127.0.0.1:8000`) while you shop online at **Amazon Fresh / Whole Foods** and **Safeway** (`safeway.com`).

When you view a product page or highlight a product name, TruePriceMemory shows:
- What you **last paid** (store, date, and unit price)
- Your **best price across all stores** (e.g., reminding you that Schweppes Tonic Water was `$1.49` at Total Wine while browsing Amazon Fresh at `$2.29`)
- A **unit-compatible deal verdict** (`Good deal`, `Typical price`, or `Above avg`) when package sizes can be compared on the same basis (`per oz`, `per fl oz`, `per lb`, or `each`)
- **Offline fallback** using a locally cached snapshot when your server is stopped

---

## 1. Quick Start (Windows & macOS)

### Step 1: Generate a Read-Only API Token
1. Start your local **IHaveTheReceipts** server (`http://127.0.0.1:8000`).
2. Open [http://127.0.0.1:8000/settings](http://127.0.0.1:8000/settings) and scroll to **TruePriceMemory Browser Extension**.
3. Enter a label (for example, `MacBook Chrome` or `Windows Firefox`) and click **Generate Token**.
4. Copy the `tpm_...` token immediately — it is shown once and stored as a SHA-256 hash on the server.

### Step 2: Load the Extension

Pre-built unpacked bundles are committed at `extension/dist/chrome` and `extension/dist/firefox` (no Node or npm install required to load them).

#### Google Chrome / Brave / Edge (Windows & macOS)
1. Open `chrome://extensions`.
2. Enable **Developer mode** (top-right toggle).
3. Click **Load unpacked** and select `extension/dist/chrome`.

#### Mozilla Firefox (Windows & macOS)
1. Open `about:debugging#/runtime/this-firefox`.
2. Click **Load Temporary Add-on…** and select `extension/dist/firefox/manifest.json`.

### Step 3: Connect & Sync Offline Snapshot
1. Click the **TruePriceMemory** toolbar icon and click the gear icon (`⚙️`) to open **Extension Options**.
2. Confirm **Server URL** is `http://127.0.0.1:8000` (works natively on macOS and via WSL2 localhost forwarding on Windows).
3. Paste your `tpm_...` token and click **Save & Test Connection**.
4. Saving and testing automatically syncs your offline snapshot (`Offline snapshot: N items cached`). You can also click **Sync Offline Snapshot** at any time.

---

## 2. How to Use While Shopping

1. **Automatic Product Page Badge (Amazon Fresh, Whole Foods on Amazon, Safeway)**:
   - Open any product detail page on `amazon.com` or `safeway.com`.
   - A compact dark-mode badge (`🧾 TruePriceMemory`) appears in the bottom-right corner with your last paid price, best store price, and unit-price deal verdict.
   - Click `×` on the badge to dismiss it for that product.
2. **Right-Click Selection Lookup (Any Page)**:
   - Highlight any product title on any webpage, right-click, and choose **Look up "…" in TruePriceMemory**.
3. **Toolbar Popup Search**:
   - Click the **TruePriceMemory** icon in your browser toolbar to search any item, filter by store, or enter a page price for an instant deal comparison.

---

## 3. Architecture & Security Model

- **Read-Only Bearer Tokens (`api_tokens` table)**:
  - Tokens are generated with `secrets.token_urlsafe(32)` (`tpm_` prefix) and hashed at rest with `hashlib.sha256`.
  - Verification uses constant-time `hmac.compare_digest`.
  - Revoking a token in Settings takes effect immediately (`401 Unauthorized`).
- **Zero CORS Exposure**:
  - `/api/ext/*` routes do **not** enable `Access-Control-Allow-Origin`. Only the browser extension (via its MV3 `host_permissions` in the background worker) can read responses; arbitrary webpages cannot probe your local server.
- **Anti-Bot & Hydration Safety**:
  - The content script (`extension/src/content/content_script.js`) is 100% passive: it reads JSON-LD (`<script type="application/ld+json">`) first and falls back to read-only DOM selectors.
  - It never issues synthetic `fetch`/`XHR` calls to the retailer and renders its badge inside a **closed Shadow DOM** (`mode: "closed"`) attached to `document.body` so retailer React/Next hydration is never disturbed.
- **Data Minimization**:
  - Responses never include `image_path`, `ocr_data`, order numbers, or filesystem paths, and all `/api/ext/*` responses set `Cache-Control: no-store`.

---

## 4. API Endpoints (`/api/ext/*`)

| Endpoint | Method | Auth | Purpose |
| :--- | :--- | :--- | :--- |
| `/api/ext/ping` | `GET` | `Bearer tpm_...` | Connectivity and token check (`{ ok, app, version }`) |
| `/api/ext/lookup` | `GET` | `Bearer tpm_...` | Retail title / GTIN lookup with unit-price comparison and store stats |
| `/api/ext/snapshot` | `GET` | `Bearer tpm_...` | Compact item + store summary snapshot for offline extension fallback |

---

## 5. Development & Testing

After editing files in `extension/src/`, rebuild the Chrome and Firefox bundles and run the zero-dependency Node test suite:

```bash
node extension/scripts/build.mjs
node --test extension/tests/common.test.mjs extension/tests/extractors.test.mjs
```

Backend tests covering token authentication, retail title matching, unit-price comparison, offline snapshots, and extension bundle verification live in:
- `backend/tests/test_ext_api_token.py`
- `backend/tests/test_ext_lookup.py`
- `backend/tests/test_extension_core.py`
