import os

import pytest
from playwright.sync_api import sync_playwright


@pytest.fixture(scope="session")
def server_url():
    """Returns the URL of the running server. Defaults to localhost:8000."""
    return os.getenv("TEST_SERVER_URL", "http://127.0.0.1:8000")


@pytest.mark.e2e
def test_store_history_modal_opens(server_url):
    """
    E2E Test: Verifies that clicking the 'Spend by Store' history button
    successfully opens the modal without JavaScript errors.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Navigate to the dashboard
        print(f"Navigating to {server_url} ...")
        response = page.goto(server_url)
        assert response.status == 200, f"Failed to load page: {response.status}"

        # Verify title
        title = page.title()
        print(f"Actual page title: '{title}'")
        assert "Dashboard" in title

        # Wait for the "Spend by Store" table to load (HTMX)
        print("Waiting for store history buttons...")
        page.wait_for_selector("button[onclick^='showStoreHistory']", timeout=10000)

        # Click the first store's history button
        button = page.query_selector("button[onclick^='showStoreHistory']")
        assert button is not None, "Store history button should exist"
        print("Clicking button...")
        button.click()

        # Assert the modal is visible
        print("Waiting for modal...")
        modal = page.wait_for_selector("#store-history-modal", state="visible", timeout=5000)
        assert modal is not None, "Store history modal should be visible after click"

        # Verify modal title is updated
        title_text = page.inner_text("#modal-title")
        print(f"Modal title text: {title_text}")
        assert "SPENDING HISTORY" in title_text.upper()

        browser.close()
