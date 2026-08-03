"""Automated accessibility smoke tests using axe-core over a live server.

Opt-in only (`uv run pytest -m e2e`) — needs a running app, same pattern as
test_dashboard_ui.py. Scans the main pages plus two id-parameterized pages
(item insights, receipt review) for axe-core violations at "serious" or
"critical" impact — the levels that reliably block screen-reader/keyboard
users, as opposed to "moderate"/"minor" advisory findings.

`color-contrast` is excluded from the scan: token-level contrast is already
guarded by scripts/check_contrast.py (WCAG AA, all 4 themes). The remaining
gap — chart-fill and badge pixel contrast — is a distinct, already-tracked
effort (see ROADMAP.md's "Deferred: chart-fill label contrast") and not what
this harness exists to catch.
"""

import json
import os

import pytest
from axe_core_python.sync_playwright import Axe
from playwright.sync_api import sync_playwright

SEVERE_IMPACTS = {"critical", "serious"}

AXE_OPTIONS = {"rules": {"color-contrast": {"enabled": False}}}
AXE_OPTIONS_JSON = json.dumps(AXE_OPTIONS)

STATIC_PAGES = ["/", "/trends", "/settings", "/categories", "/restock", "/receipts"]


@pytest.fixture(scope="session")
def server_url():
    """Returns the URL of the running server. Defaults to localhost:8000."""
    return os.getenv("TEST_SERVER_URL", "http://127.0.0.1:8000")


@pytest.fixture(scope="session")
def axe_script():
    return Axe().axe_script


def _severe_violations(results: dict) -> list[dict]:
    return [v for v in results["violations"] if v["impact"] in SEVERE_IMPACTS]


def _format_violations(violations: list[dict]) -> str:
    lines = []
    for v in violations:
        targets = ", ".join(n["target"][0] for n in v["nodes"][:3])
        lines.append(
            f"  [{v['impact']}] {v['id']}: {v['help']} ({len(v['nodes'])} node(s): {targets})"
        )
    return "\n".join(lines)


def _scan(page, axe_script: str, url: str) -> dict:
    # `networkidle` is unreliable on this app — some pages kick off slow
    # background htmx requests on hidden tabs (e.g. items.html preloads its
    # Duplicates tab even while hidden) that never let the network go quiet.
    # A fixed settle window after "load" is a bounded, deterministic stand-in.
    page.goto(url, wait_until="load")
    page.wait_for_timeout(1500)
    page.evaluate(axe_script)
    results: dict = page.evaluate(f"axe.run(document, {AXE_OPTIONS_JSON})")
    return results


def _find_scannable_items_url(page, server_url: str, max_nodes: int = 6000) -> str | None:
    """/items has no pagination and renders every item as a card with a
    13-option category <select> each — on a real install that's tens of
    thousands of DOM nodes, which axe-core cannot scan in reasonable time.
    Find a small non-empty category to scan instead; the per-item card
    markup is identical regardless of category."""
    for category_id in range(1, 21):
        url = f"{server_url}/items?category={category_id}"
        page.goto(url, wait_until="load")
        page.wait_for_timeout(1000)
        node_count = page.evaluate("document.querySelectorAll('*').length")
        if 0 < node_count <= max_nodes:
            return url
    return None


@pytest.mark.e2e
@pytest.mark.parametrize("path", STATIC_PAGES)
def test_page_has_no_severe_a11y_violations(server_url, axe_script, path):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        results = _scan(page, axe_script, server_url + path)
        browser.close()

    severe = _severe_violations(results)
    assert not severe, f"Accessibility violations on {path}:\n{_format_violations(severe)}"


@pytest.mark.e2e
def test_items_page_has_no_severe_a11y_violations(server_url, axe_script):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        url = _find_scannable_items_url(page, server_url)
        if url is None:
            browser.close()
            pytest.skip("No small-enough category found to scan /items")
        results = _scan(page, axe_script, url)
        browser.close()

    severe = _severe_violations(results)
    assert not severe, f"Accessibility violations on {url}:\n{_format_violations(severe)}"


@pytest.mark.e2e
def test_item_insights_page_has_no_severe_a11y_violations(server_url, axe_script):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        list_url = _find_scannable_items_url(page, server_url)
        if list_url is None:
            browser.close()
            pytest.skip("No items available to test the insights page")
        link = page.query_selector("a[href*='/insights']")
        if link is None:
            browser.close()
            pytest.skip("No items with an insights link available")
        href = link.get_attribute("href")
        results = _scan(page, axe_script, server_url + href)
        browser.close()

    severe = _severe_violations(results)
    assert not severe, f"Accessibility violations on {href}:\n{_format_violations(severe)}"


@pytest.mark.e2e
def test_receipt_review_page_has_no_severe_a11y_violations(server_url, axe_script):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(server_url + "/receipts", wait_until="load")
        page.wait_for_timeout(1500)
        link = page.query_selector("a[href*='/review']")
        if link is None:
            browser.close()
            pytest.skip("No receipts with a review link available")
        href = link.get_attribute("href")
        results = _scan(page, axe_script, server_url + href)
        browser.close()

    severe = _severe_violations(results)
    assert not severe, f"Accessibility violations on {href}:\n{_format_violations(severe)}"
