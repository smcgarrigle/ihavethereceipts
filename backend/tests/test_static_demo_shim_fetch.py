"""The static demo's read-only shim blocks the app's writes, not third-party POSTs.

DEMO_SHIM originally rejected every non-GET fetch. GA4 sends its hits as fetch
POSTs to google-analytics.com, so the Pages demo loaded GTM and gtag.js, set
the _ga cookies, and never sent a single hit.
"""

import ast
from pathlib import Path

import pytest

BUILDER = Path(__file__).resolve().parent.parent / "scripts" / "build_static_demo.py"
ORIGIN = "https://demo.example"


def _demo_shim() -> str:
    for node in ast.parse(BUILDER.read_text()).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "DEMO_SHIM":
            return str(ast.literal_eval(node.value))
    raise AssertionError("build_static_demo.py no longer defines DEMO_SHIM")


@pytest.fixture(scope="module")
def page():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # browser binaries not installed
            pytest.skip(f"chromium unavailable: {exc}")
        pg = browser.new_page()
        html = "<html><body>" + _demo_shim() + "</body></html>"
        # Every request is answered locally; nothing leaves the machine.
        pg.route(
            "**/*",
            lambda r: r.fulfill(
                body=html if r.request.url == ORIGIN + "/" else "ok",
                content_type="text/html",
                headers={"Access-Control-Allow-Origin": "*"},
            ),
        )
        pg.goto(ORIGIN + "/")
        yield pg
        browser.close()


def _fetch(page, expr: str) -> str:
    return str(page.evaluate(f"{expr}.then(() => 'sent', e => 'blocked')"))


@pytest.mark.parametrize(
    "expr",
    [
        "fetch('/api/items', {method: 'POST'})",
        "fetch('" + ORIGIN + "/api/items/1', {method: 'DELETE'})",
        "fetch(new Request('/api/items', {method: 'PUT'}))",
    ],
)
def test_same_origin_writes_stay_blocked(page, expr):
    assert _fetch(page, expr) == "blocked"


def test_cross_origin_post_passes_through(page):
    expr = (
        "fetch('https://www.google-analytics.com/g/collect?v=2', {method: 'POST', mode: 'no-cors'})"
    )
    assert _fetch(page, expr) == "sent"


def test_gets_pass_through(page):
    assert _fetch(page, "fetch('/api/items')") == "sent"
