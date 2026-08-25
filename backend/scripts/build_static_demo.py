"""build_static_demo.py — Freeze the app into a fully static, hostable demo site.

Creates a throwaway SQLite database, boots the FastAPI app in-process (Alembic
migrations run automatically at startup), seeds it with the fictional demo data
from seed_demo.py, then crawls every page, HTMX fragment, and JSON endpoint the
UI touches, saving each response to disk. The result is a browsable snapshot of
the whole app — dashboard, receipts, item insights, trends, predictions, X-Ray —
with zero server required.

What makes the snapshot work statically:
- HTMX GET fragments are saved at their literal URL paths, so hx-get requests
  resolve to real files.
- Static file servers ignore query strings, which would make every filtered
  request re-serve the unfiltered snapshot — the charts would redraw with
  identical data and no error. So each filter combination is pre-rendered to
  its own file under api-variants/, and a shim rewrites matching fetch() and
  XHR requests to that file. See PARAM_MATRIX.
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
import hashlib
import itertools
import json
import os
import re
import shutil
import sys
import tempfile
from collections import deque
from pathlib import Path
from urllib.parse import quote, urlencode

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
    "/help/api-keys",
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

# --- Filter variants ---------------------------------------------------------
# Static hosts ignore query strings, so `?time_range=all` would silently re-serve
# the unfiltered snapshot — charts redraw with identical data and the UI looks
# broken in the worst way (no error, just a filter that does nothing). Instead we
# pre-render every filter combination the UI can request to its own file and ship
# a URL->file map; a client-side shim rewrites matching requests to that file.
#
# These values must mirror the controls in templates/pages/trends.html: the
# time_range <select>, the setTimeRange/setUsdaTimeRange/setNutrient buttons.
# check_param_matrix() re-derives them from the template and warns on drift.
TIME_RANGES = ["3m", "6m", "ytd", "year", "all"]
USDA_TIME_RANGES = ["3m", "6m", "year", "all"]
NUTRIENTS = ["sodium", "sugar", "fat", "protein"]

# (path, {param: [values]}) — expanded to the full cartesian product.
PARAM_MATRIX: list[tuple[str, dict[str, list[str]]]] = [
    (
        "/api/trends/fragment/all-charts",
        {
            "time_range": TIME_RANGES,
            "usda_time_range": USDA_TIME_RANGES,
            "nutrient_type": NUTRIENTS,
        },
    ),
    (
        "/api/trends/nutrition-trends",
        {"time_range": TIME_RANGES, "nutrient_type": NUTRIENTS},
    ),
    ("/api/trends/usda-product-types", {"time_range": USDA_TIME_RANGES}),
]

# No leading underscore: GitHub Pages runs Jekyll, which skips _-prefixed paths.
VARIANT_DIR = "api-variants"
API_MAP_FILE = "api-map.js"

# Bare-root links ("/" and "/?x=1") for --base-path hosting. The main rewrite
# anchors on a known top-level directory name, which these have no room for, so
# they need their own pass or the wordmark and Dashboard link escape the
# subdirectory and land on the host root.
#
# Anchored to attributes and URL assignments on purpose: a blanket rule for any
# quoted "/" would also hit string literals that are not URLs. The pages contain
# `e.key === '/'` (the press-/-to-search shortcut), which such a rule would
# silently break.
ROOT_PATTERNS = [
    re.compile(r'(?P<lead>(?:href|src|action|hx-get|hx-post)=")/(?=[?#"])'),
    re.compile(
        r"""(?P<lead>(?:fetch\(|window\.location(?:\.href)?\s*=|location(?:\.href)?\s*=)\s*['"])/(?=[?#'"])"""
    ),
]

# Redirect filtered requests to their pre-rendered variant file. Static hosts
# ignore query strings, so without this a filter change re-serves the base
# snapshot and silently displays unfiltered data. Both transports need patching:
# chart data uses fetch(), the trends filter form uses htmx (XHR).
API_MAP_SHIM = """
<script src="/api-map.js"></script>
<script>
(function () {
  var MAP = window.__DEMO_API_MAP__ || {};

  // Canonical key: pathname + query sorted by name, matching the build side.
  function resolve(url) {
    try {
      var u = new URL(url, window.location.href);
      if (!u.search) return null;
      var keys = [];
      u.searchParams.forEach(function (_v, k) {
        if (keys.indexOf(k) === -1) keys.push(k);
      });
      keys.sort();
      var qs = keys.map(function (k) {
        return encodeURIComponent(k) + '=' + encodeURIComponent(u.searchParams.get(k));
      }).join('&');
      return MAP[u.pathname + '?' + qs] || null;
    } catch (e) {
      return null;
    }
  }

  var realFetch = window.fetch;
  window.fetch = function (input, init) {
    var url = (typeof input === 'string') ? input : (input && input.url);
    var hit = url ? resolve(url) : null;
    if (hit) return realFetch.call(this, hit, init);
    return realFetch.apply(this, arguments);
  };

  var realOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url) {
    var hit = (String(method).toUpperCase() === 'GET' && url) ? resolve(url) : null;
    var args = Array.prototype.slice.call(arguments);
    if (hit) args[1] = hit;
    return realOpen.apply(this, args);
  };
})();
</script>
"""

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


def canonical(path: str, params: dict[str, str]) -> str:
    """URL key with query params sorted by name — the shim builds the same string.

    quote_via=quote matches JS encodeURIComponent (%20, not +), so a value with a
    space can never produce a key the shim is unable to look up.
    """
    return path + "?" + urlencode(sorted(params.items()), quote_via=quote)


def param_variants() -> list[tuple[str, dict[str, str]]]:
    """Every (path, params) combination the filter UI can request."""
    from app.database import SessionLocal
    from app.models import Store

    db = SessionLocal()
    try:
        store_ids = [str(sid) for (sid,) in db.query(Store.id)]
    finally:
        db.close()

    matrix = [
        *PARAM_MATRIX,
        # store_id is data-dependent, so it is expanded from the seeded DB.
        (
            "/api/trends/store-top-items",
            {"store_id": store_ids, "time_range": TIME_RANGES},
        ),
    ]

    variants: list[tuple[str, dict[str, str]]] = []
    for path, spec in matrix:
        names = list(spec)
        for combo in itertools.product(*(spec[n] for n in names)):
            variants.append((path, dict(zip(names, combo, strict=True))))
    return variants


def crawl_variants(out: Path, client) -> tuple[dict[str, str], list[str]]:
    """Render each filter combination to its own file; return the URL->file map."""
    api_map: dict[str, str] = {}
    warnings: list[str] = []
    (out / VARIANT_DIR).mkdir(parents=True, exist_ok=True)

    for path, params in param_variants():
        resp = client.get(path, params=params)
        if resp.status_code != 200:
            warnings.append(f"{resp.status_code} {canonical(path, params)}")
            continue
        key = canonical(path, params)
        ext = ".json" if "json" in resp.headers.get("content-type", "") else ".html"
        name = hashlib.sha1(key.encode()).hexdigest()[:16] + ext
        (out / VARIANT_DIR / name).write_bytes(resp.content)
        api_map[key] = f"/{VARIANT_DIR}/{name}"

    return api_map, warnings


def write_api_map(out: Path, api_map: dict[str, str]) -> None:
    """Emit the map as a plain script so it is parsed before any request fires."""
    payload = json.dumps(api_map, separators=(",", ":"), sort_keys=True)
    (out / API_MAP_FILE).write_text(f"window.__DEMO_API_MAP__ = {payload};\n", encoding="utf-8")


def check_param_matrix() -> list[str]:
    """Warn if trends.html offers filter values the matrix doesn't cover."""
    template = BACKEND_DIR / "templates" / "pages" / "trends.html"
    if not template.exists():
        return []
    text = template.read_text(encoding="utf-8")
    found = {
        "time_range": set(re.findall(r"setTimeRange\('([^']+)'\)", text))
        | set(re.findall(r"<option value=\"([^\"]+)\"", text)),
        "usda_time_range": set(re.findall(r"setUsdaTimeRange\('([^']+)'\)", text)),
        "nutrient_type": set(re.findall(r"setNutrient\('([^']+)'\)", text)),
    }
    covered = {
        "time_range": set(TIME_RANGES),
        "usda_time_range": set(USDA_TIME_RANGES),
        "nutrient_type": set(NUTRIENTS),
    }
    return [
        f"{name}: template offers {sorted(found[name] - covered[name])} "
        f"which PARAM_MATRIX does not cover"
        for name in found
        if found[name] - covered[name]
    ]


def copy_static_assets(out: Path) -> None:
    src = BACKEND_DIR / "static"
    dest = out / "static"
    shutil.copytree(
        src,
        dest,
        ignore=lambda _dir, names: [n for n in names if n in STATIC_EXCLUDES],
        dirs_exist_ok=True,
    )


def crawl(out: Path) -> tuple[int, list[str], set[str], int]:
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

        # Rendered before the page crawl so the map file exists alongside it.
        api_map, variant_warnings = crawl_variants(out, client)
        warnings.extend(variant_warnings)
        write_api_map(out, api_map)

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
                    # API_MAP_SHIM first so DEMO_SHIM's write-blocking fetch
                    # wrapper ends up outermost and still sees every call.
                    text = text.replace("</body>", API_MAP_SHIM + DEMO_SHIM + "</body>", 1)
                dest.write_text(text, encoding="utf-8")
            else:
                dest.write_bytes(resp.content)
            saved += 1

    return saved, warnings, write_only, len(api_map)


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
        for root_pattern in ROOT_PATTERNS:
            new = root_pattern.sub(rf"\g<lead>{base}/", new)
        if new != text:
            file.write_text(new, encoding="utf-8")
            rewritten += 1
    return rewritten


def check_base_path(out: Path, base_path: str) -> list[str]:
    """Report root-relative refs the rewrite missed — they escape the subdirectory.

    A missed "/" sends the logo and Dashboard link to the host root instead of the
    project site, so this runs on every --base-path build.
    """
    base = "/" + base_path.strip("/")
    attr_ref = re.compile(r'(?:href|src|action|hx-get|hx-post)="(/[^"]*)"')
    missed: dict[str, int] = {}
    for file in out.rglob("*.html"):
        for ref in attr_ref.findall(file.read_text(encoding="utf-8")):
            if not ref.startswith(base + "/") and ref != base:
                missed[ref] = missed.get(ref, 0) + 1
    return [f'{count}x unprefixed ref "{ref}"' for ref, count in sorted(missed.items())]


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
    final_out = Path(args.out).resolve()

    # Build into a sibling staging dir and swap in only on success, so a
    # crashed build (missing deps, broken venv, ...) never destroys the
    # previous good snapshot.
    out = final_out.parent / (final_out.name + ".building")

    print(f"🏗️  Building static demo → {final_out}")
    print(f"🗄️  Throwaway database: {DEMO_DB}")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    for drift in check_param_matrix():
        print(f"  ⚠️  filter drift — {drift}")

    copy_static_assets(out)
    saved, warnings, write_only, variants = crawl(out)

    # GitHub Pages runs Jekyll by default, which would skip some paths.
    (out / ".nojekyll").write_text("", encoding="utf-8")

    if args.base_path:
        count = rewrite_base_path(out, args.base_path)
        print(f"🔗 Rewrote root-relative URLs in {count} files for base path {args.base_path!r}")
        for escaped in check_base_path(out, args.base_path):
            print(f"  ⚠️  escapes the base path — {escaped}")

    print(f"\n✅ Snapshot complete: {saved} responses saved")
    print(f"   {variants} filter variants pre-rendered into {VARIANT_DIR}/")
    print(f"   {len(write_only)} write-only/parameterized endpoints skipped (shim blocks them)")
    for warning in warnings:
        print(f"  ⚠️  {warning}")

    if not args.base_path:
        broken = check_internal_refs(out, write_only)
        if broken:
            print(f"  ⚠️  {len(broken)} internal references have no snapshot file:")
            for ref in broken[:20]:
                print(f"      {ref}")

    if final_out.exists():
        shutil.rmtree(final_out)
    out.rename(final_out)

    shutil.rmtree(_TMP_DIR, ignore_errors=True)
    print(f"\n🚀 Preview:  python3 -m http.server -d {final_out} 8080")
    return 0


if __name__ == "__main__":
    sys.exit(main())
