# 📸 The Static Demo

**Live:** https://smcgarrigle.github.io/ihavethereceipts/

A frozen, read-only copy of the whole app running on fictional data, hosted on
GitHub Pages with no server and no database. Every page, chart and tooltip is
real — it's the actual app, crawled and saved to disk.

## Build it

```bash
make demo
```

Then preview at http://127.0.0.1:8080:

```bash
python3 -m http.server -d site/demo 8080
```

## How it works

`backend/scripts/build_static_demo.py` does four things:

1. Seeds a **throwaway** SQLite database with `seed_demo.py` — 52 fictional
   receipts, 12 joke stores, ~93 items. Your real `grocery.db` is never touched.
2. Boots the FastAPI app in-process and crawls every page, HTMX fragment and
   JSON endpoint the UI touches (~352 responses) into `site/demo/`.
3. Rewrites root-relative URLs for the `/ihavethereceipts` subpath.
4. Injects small demo-only scripts (below) before `</body>`.

`site/demo/` is gitignored and **never committed** — CI rebuilds it each deploy,
so it can't go stale against the templates.

## The awkward bits

A static host has no server and ignores query strings, so three things needed
help:

- **Filters** (`?time_range=…`) would silently re-serve unfiltered data. Each
  combination is pre-rendered to `api-variants/`, and a shim redirects matching
  requests there using `api-map.js`.
- **Receipt store pills** are multi-select, so pre-rendering would mean the power
  set of 12 stores. Instead a shim filters the response client-side in
  `htmx:beforeSwap`.
- **Uploading a receipt** can't happen, so clicking Upload plays a scripted OCR
  sequence and opens a seeded receipt. It says so on screen; no file is read.

Everything else that writes is blocked with a "read-only demo" toast.

## What genuinely can't work

USDA and product-lookup searches hit live third-party APIs with unbounded
queries. Those stay unavailable.

## Deploying

`.github/workflows/pages.yml` rebuilds and publishes on every push to `main`
touching `backend/**`, or on demand from the Actions tab.

Needs one repository secret, `FDC_API_KEY`. Without it the demo still builds,
but the USDA nutrition on item pages comes out empty.

The build fails loudly rather than shipping something broken: it checks that no
link escapes the base path, that every `fetch(\`/api/…\`)` has a snapshot behind
it, and that the filter matrix still matches the template.
