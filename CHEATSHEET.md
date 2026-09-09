# IHaveTheReceipts - Cheatsheet
For AI agent behavior and coding style, see [GEMINI.md](GEMINI.md).

## 🚀 Application Management

### Start the Application
The most reliable way to start the app (runs migrations + server):
```bash
cd backend
./start_server.sh
```

**Alternative (Direct Uvicorn):**
```bash
cd backend
source .venv/bin/activate  # If not already active
uvicorn app.main:app --reload --port 8000
```

### Stop the Application
- **If running in terminal:** Press `Ctrl + C`
- **If running in background:**
  ```bash
  pkill -f uvicorn
  ```

---

## 📋 Log Tracing

### Local Mode (Python/Uvicorn)
`./start_server.sh` runs uvicorn in the foreground, so request logs appear in
that terminal window. There is no `uvicorn_log.txt` — nothing writes one.

The background bulk worker is the one component that does log to a file:
```bash
# Follow the OCR queue in real-time
tail -f data/bulk.log
```
---

## 🛠️ Troubleshooting

### Clear a Used Port (Address already in use)
If port `8000` is blocked:

**1. Find the Process ID (PID):**
```bash
lsof -i :8000
# OR
netstat -ltnp | grep 8000
```

**2. Kill the Process:**
```bash
kill -9 <PID>
```

**One-line Force Kill:**
```bash
fuser -k 8000/tcp
```

### Broken venv / Wrong Python (ImportError: cannot import name 'UTC')
Dev tools (pytest/ruff/mypy) live in the `dev` **extra** — plain `uv sync` removes them, and `uv run pytest` then silently falls back to system Python 3.10, which fails on `datetime.UTC` imports. A crashed/interrupted `uv` can also leave `.venv/bin` with only `activate` scripts. Either way:
```bash
cd backend
rm -rf .venv && uv sync --extra dev
```

---

## 🔍 Diagnostics

### Determine Database Mode

**Check Configuration:**
Look at `.env`:
```bash
cat .env | grep DATABASE_URL
```
- Should always be `sqlite:///...` → **Running with SQLite (Local)**

---

## 🎨 Frontend CSS (Precompiled Tailwind)

Rebuild after adding/changing Tailwind classes in templates (new classes render unstyled until rebuilt):
```bash
cd backend
./scripts/build_css.sh          # fetches the pinned CLI on first run, writes static/css/tailwind.css
```

## 📸 Static Demo Site

Live at **https://smcgarrigle.github.io/ihavethereceipts/**, rebuilt by GitHub
Actions on every push to `main` that touches `backend/**`. See [DEMO.md](DEMO.md)
for how it works and what it can't do.

### Build the Demo Snapshot
Seeds a throwaway DB (never touches `grocery.db`) and bakes the whole app into `site/demo`. Builds are atomic — a crashed build leaves the previous snapshot intact.
```bash
make demo                      # from repo root
# equivalent: cd backend && uv run python scripts/build_static_demo.py
```

For subdirectory hosting (e.g. GitHub Pages project site at `/repo-name/`):
```bash
cd backend
uv run python scripts/build_static_demo.py --base-path /repo-name
```

### Serve It Locally
```bash
python3 -m http.server -d site/demo 8080   # from repo root → http://127.0.0.1:8080
```

### Reach It From Your Own Devices (Tailscale)
`tailscale serve` currently proxies **port 8000 — the main app**, tailnet-only. It
is not pointed at the demo.
```bash
tailscale serve status                     # what is actually proxied right now
tailscale serve --bg 8080                  # repoint at the demo instead
```

> ⚠️ **Do not reach for `tailscale funnel` here.** Funnel publishes to the open
> internet, and this app has **no authentication at all** — see
> [SECURITY.md](SECURITY.md). Funnel is deliberately off. If you want the demo
> public, use the GitHub Pages build above: it is a read-only snapshot of
> fictional data, with no server and no database behind it.

---

## 🧠 Local AI & OCR (LM Studio / Ollama)

### Reprocess a Receipt (Model Testing)
Use this to test the local model on an existing receipt image:
```bash
cd backend
./.venv/bin/python3 scripts/reprocess_receipt.py <RECEIPT_ID>
```

### Measure OCR Accuracy (Eval Harness)
Scores extraction accuracy against your own human-reviewed receipts:
```bash
cd backend
uv run python scripts/ocr_eval.py                  # free baseline from stored extractions
uv run python scripts/ocr_eval.py --live --limit 5 # re-run OCR with current prompt/model
```

### Inspect What the OCR Has Learned
The feedback loop stores your review corrections and feeds them into future prompts:
```bash
sqlite3 grocery.db "SELECT field, ai_value, approved_value FROM ocr_corrections ORDER BY id DESC LIMIT 20;"
# the database lives at the repository root, so from backend/: sqlite3 ../grocery.db "..."
```

### Monitor GPU Usage
Check if the model is actually running on your NVIDIA GPU:
```bash
# General GPU status
nvidia-smi

# LM Studio: GPU usage visible in the LM Studio app status bar
# Ollama: check CPU/GPU split
ollama ps
```

### Fix "GPU Access Blocked" / CPU-only fallback (Ollama)
If `ollama ps` shows 100% CPU despite having a GPU:

1. **Edit the Service**:
   ```bash
   sudo systemctl edit ollama.service
   ```
2. **Add the environment override**:
   ```ini
   [Service]
   Environment="LD_LIBRARY_PATH=/usr/lib/wsl/lib"
   ```
3. **Reload & Restart**:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart ollama
   ```

---

## 🧹 Data Maintenance Scripts

All scripts live in `backend/scripts/` and use `grocery.db` directly. Run from `backend/`.

### Backfill Unit Prices (Saved ReceiptItems)
Recomputes `unit_price` (and the per-quantity `price`) in the `receipt_items`
table from the pricing breakdown in each line's `notes` JSON. `price` stays the
per-quantity price that spend is read from; only `unit_price` carries the
per-pound figure for bulk lines. Always `--dry-run` first.
```bash
uv run python scripts/backfill_unit_prices.py [--dry-run]
```

### One-off cleanup scripts (archived)

Four scripts that used to be listed here — `patch_receipt_ocr.py`,
`fix_batch_dates.py`, `fix_dirty_names.py` and `fix_store_names.py` — were
written for the May 2026 batch import cleanup and have moved to
`backend/scripts/archive/`. They still run, but they are historical one-offs
rather than maintenance you should reach for, and they are not covered by the
test suite. Read one before running it.

Current store-name normalisation lives in `scripts/normalize_stores.py`.
