"""build_static_demo.py — Freeze the app into a fully static, hostable demo site.

Creates a throwaway SQLite database, boots the FastAPI app in-process (Alembic
migrations run automatically at startup), seeds it with the fictional demo data
from seed_demo.py, then crawls every page, HTMX fragment, and JSON endpoint the
UI touches, saving each response to disk. The result is a browsable snapshot of
the whole app — dashboard, receipts, item insights, trends, predictions, X-Ray —
with zero server required.

What makes the snapshot work statically:
- HTMX GET fragments are saved at their literal URL paths, so hx-get requests
  resolve to real files. Static file servers ignore query strings, so filter
  re-requests (e.g. trends date ranges) re-serve the base snapshot instead of
  404ing.
- A "demo mode" shim is injected into every page: it blocks non-GET requests
  (HTMX or fetch), blocks form submissions, and shows a toast explaining that
  the demo is read-only.
- With --base-path, root-relative URLs are rewritten for subdirectory hosting
  (e.g. GitHub Pages project sites).

Usage:
    cd backend
    uv run python scripts/build_static_demo.py                # → ../site/demo
    uv run python scripts/build_static_demo.py --out /tmp/demo --base-path /grocery-tracker/demo

The live database is never touched: DATABASE_URL is pointed at a temp file
before the app is imported, and config.py loads .env with override=False so the
redirect sticks.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
from collections import deque
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent

# --- Environment must be set before any app import ---------------------------
_TMP_DIR = Path(tempfile.mkdtemp(prefix="static-demo-"))
DEMO_DB = _TMP_DIR / "demo.db"
os.environ["DATABASE_URL"] = f"sqlite:///{DEMO_DB}"
os.environ["FOLDER_WATCH"] = "0"  # no inbox watcher during the build
os.environ["OCR_BACKEND"] = "local"  # skip Gemini model validation at startup
os.environ.setdefault("SECRET_KEY", "static-demo-build-key")

sys.path.insert(0, str(BACKEND_DIR))

# Page routes that exist regardless of data (entity pages are added from the DB).
SEED_URLS = [
    "/",
    "/receipts",
    "/receipts/bulk",
    "/items",
    "/categories",
    "/trends",
    "/xray",
    "/restock",
    "/produce",
    "/settings",
    "/styleguide",
    "/demo-bi",
    "/search",
    "/best-value/produce",
    "/favicon.ico",
]

# URL discovery inside crawled documents: attributes, fetch() calls, and
# hard-coded client-side redirects. Only root-relative, fully-rendered URLs.
URL_PATTERNS = [
    re.compile(r'(?:href|src|action|hx-get)="(/[^"{}\s]*)"'),
    re.compile(r"""fetch\(\s*['"](/[^'"{}\s]+)['"]"""),
    re.compile(r"""window\.location(?:\.href)?\s*=\s*['"](/[^'"{}\s]+)['"]"""),
]

SKIP_PREFIXES = ("/api/export",)  # download endpoints; pointless in a snapshot
STATIC_EXCLUDES = {"uploads", "duplicates_report.html", "other_categories.html"}

DEMO_SHIM = """
<div id="static-demo-badge" style="position:fixed;bottom:14px;right:14px;z-index:9999;
  background:#1c2733;color:#e6edf3;border:1px solid #30475e;border-radius:999px;
  padding:7px 14px;font:600 12px/1.4 system-ui,sans-serif;box-shadow:0 4px 14px rgba(0,0,0,.4);
  opacity:.92;pointer-events:none;">📸 Static demo — fictional data, read-only</div>
<script>
(function () {
  var badge = document.getElementById('static-demo-badge');
  var timer = null;
  function toast(msg) {
    badge.textContent = msg;
    badge.style.background = '#5c2b29';
    badge.style.borderColor = '#a2453f';
    clearTimeout(timer);
    timer = setTimeout(function () {
      badge.textContent = '\\ud83d\\udcf8 Static demo \\u2014 fictional data, read-only';
      badge.style.background = '#1c2733';
      badge.style.borderColor = '#30475e';
    }, 2600);
  }
  document.body.addEventListener('htmx:beforeRequest', function (e) {
    var cfg = e.detail.requestConfig;
    if (cfg && cfg.verb && cfg.verb.toLowerCase() !== 'get') {
      e.preventDefault();
      toast('Read-only demo \\u2014 editing is disabled');
    }
  });
  document.body.addEventListener('htmx:responseError', function () {
    toast('Not available in the static demo');
  });
  document.addEventListener('submit', function (e) {
    e.preventDefault();
    e.stopPropagation();
    toast('Read-only demo \\u2014 forms are disabled');
  }, true);
  var realFetch = window.fetch;
  window.fetch = function (url, opts) {
    if (opts && opts.method && opts.method.toUpperCase() !== 'GET') {
      toast('Read-only demo \\u2014 editing is disabled');
      return Promise.reject(new Error('static demo: write blocked'));
    }
    return realFetch.apply(this, arguments);
  };
})();
</script>
"""


def is_page(path: str) -> bool:
    """HTML documents get directory-style output; fragments/JSON keep literal paths."""
    return not path.startswith(("/api/", "/settings/", "/static/", "/uploads/"))


def output_path(out: Path, url_path: str, content_type: str) -> Path:
    rel = url_path.lstrip("/")
    if url_path == "/":
        return out / "index.html"
    if "text/html" in content_type and is_page(url_path) and "." not in rel.rsplit("/", 1)[-1]:
        return out / rel / "index.html"
    return out / rel


def discover(text: str) -> set[str]:
    found: set[str] = set()
    for pat in URL_PATTERNS:
        for match in pat.findall(text):
            path = match.split("?")[0].split("#")[0].rstrip()
            if not path or path == "/" or path.startswith("//"):
                continue
            if any(path.startswith(p) for p in SKIP_PREFIXES):
                continue
            found.add(path)
    return found


def seed_database() -> None:
    """Run seed_demo.py in-process against the (already migrated) demo DB."""
    sys.path.insert(0, str(BACKEND_DIR / "scripts"))
    import seed_demo

    seed_demo.seed()


def entity_urls() -> list[str]:
    from app.database import SessionLocal
    from app.models import Item, Receipt

    db = SessionLocal()
    try:
        urls = [f"/items/{item_id}/insights" for (item_id,) in db.query(Item.id)]
        urls += [f"/receipts/{receipt_id}/review" for (receipt_id,) in db.query(Receipt.id)]
        # JSON consumed by the price-history modal's runtime fetch() — the URL is
        # built in a JS template literal, so the crawler's regexes never see it.
        urls += [f"/api/analytics/price-trends/{item_id}" for (item_id,) in db.query(Item.id)]
        return urls
    finally:
        db.close()


def copy_static_assets(out: Path) -> None:
    src = BACKEND_DIR / "static"
    dest = out / "static"
    shutil.copytree(
        src,
        dest,
        ignore=lambda _dir, names: [n for n in names if n in STATIC_EXCLUDES],
        dirs_exist_ok=True,
    )


def crawl(out: Path) -> tuple[int, list[str], set[str]]:
    from fastapi.testclient import TestClient

    from app.main import app

    saved = 0
    warnings: list[str] = []
    write_only: set[str] = set()
    queue: deque[str] = deque(SEED_URLS)
    visited: set[str] = set(SEED_URLS)

    with TestClient(app) as client:
        seed_database()
        for url in entity_urls():
            if url not in visited:
                visited.add(url)
                queue.append(url)

        while queue:
            path = queue.popleft()
            if path.startswith(("/static/", "/uploads/")):
                continue  # static assets are copied wholesale, uploads excluded
            resp = client.get(path, follow_redirects=True)
            if resp.status_code in (405, 422):
                # Write-only endpoints (hx-post/PUT/DELETE targets picked up by the
                # URL regex) or GETs needing query params. The demo shim blocks
                # these client-side, so a missing snapshot is expected.
                write_only.add(path)
                continue
            if resp.status_code != 200:
                warnings.append(f"{resp.status_code} {path}")
                continue

            content_type = resp.headers.get("content-type", "")
            dest = output_path(out, path, content_type)
            dest.parent.mkdir(parents=True, exist_ok=True)

            if "text/html" in content_type:
                text = resp.text
                for found in discover(text):
                    if found not in visited:
                        visited.add(found)
                        queue.append(found)
                if is_page(path):
                    text = text.replace("</body>", DEMO_SHIM + "</body>", 1)
                dest.write_text(text, encoding="utf-8")
            else:
                dest.write_bytes(resp.content)
            saved += 1

    return saved, warnings, write_only


def rewrite_base_path(out: Path, base_path: str) -> int:
    """Rewrite root-relative URLs for subdirectory hosting (e.g. GitHub Pages)."""
    base = "/" + base_path.strip("/")
    prefixes = sorted({p.name for p in out.iterdir() if p.name != "index.html"} | {"favicon.ico"})
    alternation = "|".join(map(re.escape, prefixes))
    # Opening delimiters include the backtick so template-literal URLs
    # (e.g. fetch(`/api/analytics/price-trends/${itemId}`)) are rewritten too.
    pattern = re.compile(rf"""(?P<q>["'(`])/(?P<path>(?:{alternation})(?:[/?"'#)`]|$))""")
    rewritten = 0
    for file in out.rglob("*"):
        if file.is_dir() or file.suffix in {".png", ".svg", ".woff", ".woff2", ".ico"}:
            continue
        try:
            text = file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        new = pattern.sub(lambda m: m.group("q") + base + "/" + m.group("path"), text)
        if new != text:
            file.write_text(new, encoding="utf-8")
            rewritten += 1
    return rewritten


def check_internal_refs(out: Path, expected_missing: set[str]) -> list[str]:
    """Report root-relative references that don't resolve to a snapshot file."""
    missing: set[str] = set()
    for html in out.rglob("*.html"):
        for ref in discover(html.read_text(encoding="utf-8")):
            if ref in expected_missing:
                continue
            rel = ref.lstrip("/")
            candidates = (out / rel, out / rel / "index.html")
            if not any(c.exists() for c in candidates):
                missing.add(ref)
    return sorted(missing)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", default=str(ROOT_DIR / "site" / "demo"))
    parser.add_argument(
        "--base-path",
        default="",
        help="URL prefix the demo will be hosted under, e.g. /grocery-tracker/demo",
    )
    args = parser.parse_args()
    out = Path(args.out).resolve()

    print(f"🏗️  Building static demo → {out}")
    print(f"🗄️  Throwaway database: {DEMO_DB}")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    copy_static_assets(out)
    saved, warnings, write_only = crawl(out)

    if args.base_path:
        count = rewrite_base_path(out, args.base_path)
        print(f"🔗 Rewrote root-relative URLs in {count} files for base path {args.base_path!r}")

    print(f"\n✅ Snapshot complete: {saved} responses saved")
    print(f"   {len(write_only)} write-only/parameterized endpoints skipped (shim blocks them)")
    for warning in warnings:
        print(f"  ⚠️  {warning}")

    if not args.base_path:
        broken = check_internal_refs(out, write_only)
        if broken:
            print(f"  ⚠️  {len(broken)} internal references have no snapshot file:")
            for ref in broken[:20]:
                print(f"      {ref}")

    shutil.rmtree(_TMP_DIR, ignore_errors=True)
    print(f"\n🚀 Preview:  python3 -m http.server -d {out} 8080")
    return 0


if __name__ == "__main__":
    sys.exit(main())
