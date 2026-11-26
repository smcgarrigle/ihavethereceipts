"""The processing screen prints run warnings in orange.

Opt-in (`uv run pytest -m e2e`) because it drives Chromium, but it needs no
live server: the page is rendered by the in-process TestClient and served to
the browser through route interception, and /api/receipts/{id}/status answers
from a script. Playwright's fake clock skips the animation delays.
"""

import json
from datetime import datetime
from pathlib import Path

import pytest
from playwright.sync_api import Route, sync_playwright

from app.models import Receipt

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
ORIGIN = "http://receipts.test"
ORANGE_400 = "rgb(251, 146, 60)"  # Tailwind text-orange-400

BUSY = "gemini-3.7-flash unavailable for categorization (503 UNAVAILABLE: high demand)."
# Server-supplied text must render as text, never as markup.
HOSTILE = "<img src=x onerror=\"document.body.dataset.pwned='1'\"> unavailable (500)."


@pytest.mark.e2e
def test_run_warnings_print_in_orange(client, db):
    receipt = Receipt(image_path="x.jpg", status="processing", purchase_date=datetime(2026, 1, 1))
    db.add(receipt)
    db.commit()
    html = client.get(f"/receipts/{receipt.id}/review").text
    assert "TERM // GROCERY_OCR" in html

    # Each poll gets the next answer; the last one repeats.
    polls = [
        {"status": "processing", "warnings": [BUSY + " Trying gemini-3.6-flash."]},
        {"status": "processing", "warnings": [BUSY + " Trying gemini-3.6-flash.", HOSTILE]},
        {"status": "completed", "warnings": [BUSY + " Trying gemini-3.6-flash.", HOSTILE]},
    ]
    served = {"n": 0, "pages": 0}

    def handle(route: Route) -> None:
        path = route.request.url[len(ORIGIN) :].split("?")[0]
        if path.startswith("/static/"):
            route.fulfill(path=str(STATIC_DIR / path[len("/static/") :]))
        elif path == f"/api/receipts/{receipt.id}/status":
            body = polls[min(served["n"], len(polls) - 1)]
            served["n"] += 1
            route.fulfill(content_type="application/json", body=json.dumps(body))
        elif path == f"/receipts/{receipt.id}/review":
            served["pages"] += 1
            # The reload after completion would show the review page; a stub
            # is enough to tell that it happened.
            route.fulfill(
                content_type="text/html", body=html if served["pages"] == 1 else "<p>review</p>"
            )
        else:
            route.fulfill(status=404, body="")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.clock.install()
        page.route(f"{ORIGIN}/**", handle)
        page.goto(f"{ORIGIN}/receipts/{receipt.id}/review")

        # Advance in 0.5s steps (polls are every 2s); each fetch reply arrives
        # in real time, so let it land before the next step. Steps shorter
        # than the 1.5s reload delay catch the terminal before it reloads.
        done = (
            "(document.getElementById('term-output')?.innerText ?? '')"
            ".includes('EXTRACTED')"  # scripted lines use &nbsp; between words
        )
        for _ in range(160):
            page.clock.run_for(500)
            page.wait_for_timeout(50)
            if page.evaluate(done):
                break
        assert page.evaluate(done), page.locator("#term-output").inner_text()

        # The newest lines are on screen: the box is overflow-hidden and used
        # to stay at the top, cutting off everything past the first screenful.
        box = page.locator("#term-output").bounding_box()
        last = page.locator("#term-output div").last.bounding_box()
        assert box and last
        assert box["y"] <= last["y"] and last["y"] + last["height"] <= box["y"] + box["height"] + 1

        warn_lines = page.locator("#term-output .text-orange-400")
        assert warn_lines.count() == 2, "each warning printed once, not once per poll"
        assert warn_lines.nth(0).inner_text() == "[WARN] " + BUSY + " Trying gemini-3.6-flash."
        assert warn_lines.nth(1).inner_text() == "[WARN] " + HOSTILE
        assert warn_lines.nth(0).evaluate("el => getComputedStyle(el).color") == ORANGE_400
        assert page.evaluate("document.body.dataset.pwned") is None
        assert page.locator("#term-output img").count() == 0

        # Warnings come before the completion lines, in arrival order.
        text = page.locator("#term-output").inner_text()
        assert text.index(BUSY) < text.index(HOSTILE[:20]) < text.index("EXTRACTED")
        browser.close()
