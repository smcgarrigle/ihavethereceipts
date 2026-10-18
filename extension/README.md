# TruePriceMemory Browser Extension

Read-only Chrome and Firefox WebExtension that connects to your local **IHaveTheReceipts** server (`http://127.0.0.1:8000`) to display prices you have previously paid across stores while shopping online.

## 1. Build Chrome & Firefox Bundles

From the repository root:

```bash
node extension/scripts/build.mjs
```

This generates:
- `extension/dist/chrome/` — Manifest V3 bundle for Chrome / Edge (Windows & macOS)
- `extension/dist/firefox/` — Manifest V3 bundle for Firefox (Windows & macOS)

## 2. Load the Extension

### Chrome / Edge (Windows & macOS)
1. Open `chrome://extensions`.
2. Enable **Developer mode** (top-right toggle).
3. Click **Load unpacked** and select the `extension/dist/chrome` folder.
   *(If your repo lives inside WSL2 on Windows, either browse to `\\wsl.localhost\<Distro>\home\...\grocery-tracker\extension\dist\chrome` or copy `dist/chrome` to a Windows folder.)*

### Firefox (Windows & macOS)
1. Open `about:debugging#/runtime/this-firefox`.
2. Click **Load Temporary Add-on…**.
3. Select `extension/dist/firefox/manifest.json`.

## 3. Connect Your Local Server

1. In the web app, open `http://127.0.0.1:8000/settings` and scroll to **TruePriceMemory Browser Extension**.
2. Click **Create token** and copy the `tpm_...` secret.
3. Click the **TruePriceMemory** extension icon &rarr; ⚙️ (**Options**), paste the token, and click **Save & Test Connection**.
4. Highlight any product name on a webpage and right-click **Look up "…" in TruePriceMemory**, or open the popup to search directly.
