"""The review page sends one save at a time.

Two saves of the same receipt race for SQLite's write lock: the second waits
out busy_timeout and fails with "database is locked" (seen on receipt 546,
Nov 2026). The page has two Save buttons and nothing stopped a second click
while the first save was still running.

Opt-in (`uv run pytest -m e2e`) because it drives Chromium, but it needs no
live server: the page is rendered by the in-process TestClient and served
through route interception. Save requests are held open by the test, so the
"still saving" window lasts as long as the test needs.
"""

import json
from datetime import datetime
from pathlib import Path

import pytest
from playwright.sync_api import Route, sync_playwright

from app.models import Receipt

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
ORIGIN = "http://receipts.test"
SAVE_BUTTONS = "button:has-text('Save Items'), button:has-text('Save All Items')"


def _review_html(client, db) -> tuple[int, str]:
    ocr = {
        "store_name": "Test Market",
        "purchase_date": "2026-01-01",
        "total_amount": 2.99,
        "items": [
            {
                "name": "Milk",
                "base_price": 2.99,
                "final_price": 2.99,
                "quantity": 1,
                "category": "Dairy",
            }
        ],
    }
    receipt = Receipt(
        image_path="x.jpg",
        status="completed",
        total_amount=2.99,  # a $0 total opens an alert modal over the page
        purchase_date=datetime(2026, 1, 1),
        ocr_data=json.dumps(ocr),
    )
    db.add(receipt)
    db.commit()
    html = client.get(f"/receipts/{receipt.id}/review").text
    assert "saveItems()" in html
    # Any detection alert opens a modal over the Save buttons.
    assert '<script id="detection-alert" type="application/json">\nnull' in html
    return receipt.id, html


def _open(p, receipt_id: int, html: str, held: list[Route]):
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.on("dialog", lambda d: d.dismiss())

    def handle(route: Route) -> None:
        path = route.request.url[len(ORIGIN) :].split("?")[0]
        if path.startswith("/static/"):
            route.fulfill(path=str(STATIC_DIR / path[len("/static/") :]))
        elif path.endswith("/save-reviewed-items"):
            held.append(route)  # answered later by the test
        elif path == f"/receipts/{receipt_id}/review":
            route.fulfill(content_type="text/html", body=html)
        elif path.startswith("/api/"):
            route.fulfill(content_type="application/json", body="[]")
        else:
            route.fulfill(content_type="text/html", body="<p>elsewhere</p>")

    page.route(f"{ORIGIN}/**", handle)
    page.goto(f"{ORIGIN}/receipts/{receipt_id}/review")
    page.wait_for_function("window.Alpine !== undefined")
    return browser, page


def _click_everything(page) -> None:
    """Every way a second save could start: both buttons, and the handler itself."""
    page.evaluate(
        """() => {
            document.querySelectorAll('button').forEach(b => {
                if (/Save (All )?Items/.test(b.textContent)) b.click();
            });
            const root = document.querySelector('[x-data^="receiptReview"]');
            Alpine.$data(root).saveItems();
        }"""
    )
    page.wait_for_timeout(300)


@pytest.mark.e2e
def test_second_save_is_not_sent_while_first_is_running(client, db):
    receipt_id, html = _review_html(client, db)
    held: list[Route] = []
    with sync_playwright() as p:
        browser, page = _open(p, receipt_id, html, held)
        page.locator("button:has-text('Save Items')").first.click()
        page.wait_for_timeout(300)
        assert len(held) == 1

        _click_everything(page)
        assert len(held) == 1, "a second save went out while the first was running"
        buttons = page.locator(SAVE_BUTTONS)
        assert buttons.count() == 2
        for i in range(2):
            assert buttons.nth(i).is_disabled()

        # A successful save redirects; the buttons stay off until it does.
        held[0].fulfill(
            content_type="application/json",
            body=json.dumps({"success": True, "items_saved": 1, "relink_suggestions": []}),
        )
        page.wait_for_timeout(300)
        _click_everything(page)
        assert len(held) == 1, "saved again during the redirect delay"
        page.wait_for_url(f"{ORIGIN}/receipts", timeout=5000)
        browser.close()


@pytest.mark.e2e
def test_failed_save_can_be_retried(client, db):
    receipt_id, html = _review_html(client, db)
    held: list[Route] = []
    with sync_playwright() as p:
        browser, page = _open(p, receipt_id, html, held)
        save = page.locator("button:has-text('Save Items')").first
        save.click()
        page.wait_for_timeout(300)
        held[0].fulfill(
            content_type="application/json",
            body=json.dumps({"success": False, "message": "database is locked"}),
        )
        page.wait_for_function(
            "[...document.querySelectorAll('button')].every(b => !b.disabled)", timeout=5000
        )
        save.click()
        page.wait_for_timeout(300)
        assert len(held) == 2
        held[1].fulfill(content_type="application/json", body=json.dumps({"success": False}))
        browser.close()
