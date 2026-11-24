"""E2E checks that the theme toggle applies each palette.

Opt-in only (`uv run pytest -m e2e`) — needs a running app, same pattern as
test_dashboard_ui.py. Set TEST_SERVER_URL to point at a non-default server.

Each step asserts both the exact class set on <html> and a computed design
token (--bg-card from static/css/themes.css), since a stray class can leave
the right theme name present while a later selector still wins the cascade.
"""

import os

import pytest
from playwright.sync_api import Page, sync_playwright

# --bg-card per theme, as defined in static/css/themes.css.
BG_CARD = {
    "light": "#ffffff",
    "dark": "#1f2937",
    "forest": "#0f1c12",
    "sunset": "#2a1a10",
}

EXPECTED_CLASSES = {
    "light": {"light"},
    "dark": {"dark"},
    "forest": {"forest", "dark"},
    "sunset": {"sunset", "dark"},
}

TOGGLE = "button[aria-label^='Switch theme']:visible"


@pytest.fixture(scope="session")
def server_url():
    """Returns the URL of the running server. Defaults to localhost:8000."""
    return os.getenv("TEST_SERVER_URL", "http://127.0.0.1:8000")


def _html_classes(page: Page) -> set[str]:
    return set(page.evaluate("Array.from(document.documentElement.classList)"))


def _bg_card(page: Page) -> str:
    return str(
        page.evaluate(
            "getComputedStyle(document.documentElement).getPropertyValue('--bg-card').trim()"
        )
    )


def _assert_theme(page: Page, theme: str) -> None:
    assert _html_classes(page) == EXPECTED_CLASSES[theme], f"<html> classes for {theme}"
    assert _bg_card(page) == BG_CARD[theme], f"--bg-card for {theme}"


def _new_page(p, *, stored_theme: str | None = None, block_alpine: bool = False):
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    if stored_theme is not None:
        context.add_init_script(f"localStorage.setItem('theme', {stored_theme!r})")
    if block_alpine:
        # Without Alpine, what renders is exactly what the server markup and
        # anything running before first paint produce — the state a visitor
        # sees until the deferred Alpine bundle initialises.
        context.route("**/alpine*.js", lambda route: route.abort())
    return browser, context.new_page()


@pytest.mark.e2e
def test_first_visit_renders_dark_before_alpine(server_url):
    """No flash of light: with nothing stored, the pre-Alpine page is dark."""
    with sync_playwright() as p:
        browser, page = _new_page(p, block_alpine=True)
        page.goto(server_url, wait_until="domcontentloaded")
        _assert_theme(page, "dark")
        browser.close()


@pytest.mark.e2e
@pytest.mark.parametrize("theme", ["light", "dark", "forest", "sunset"])
def test_stored_theme_applies_before_alpine(server_url, theme):
    """A returning visitor's stored theme is applied before first paint."""
    with sync_playwright() as p:
        browser, page = _new_page(p, stored_theme=theme, block_alpine=True)
        page.goto(server_url, wait_until="domcontentloaded")
        _assert_theme(page, theme)
        browser.close()


@pytest.mark.e2e
def test_first_visit_defaults_to_dark(server_url):
    with sync_playwright() as p:
        browser, page = _new_page(p)
        page.goto(server_url, wait_until="load")
        page.wait_for_selector(TOGGLE)
        _assert_theme(page, "dark")
        browser.close()


@pytest.mark.e2e
def test_toggle_cycles_through_every_theme(server_url):
    """light -> dark -> forest -> sunset -> light, then survives a reload."""
    with sync_playwright() as p:
        browser, page = _new_page(p)
        page.goto(server_url, wait_until="load")
        page.evaluate("localStorage.setItem('theme', 'light')")
        page.reload(wait_until="load")
        page.wait_for_selector(TOGGLE)
        _assert_theme(page, "light")

        for theme in ["dark", "forest", "sunset", "light"]:
            page.click(TOGGLE)
            page.wait_for_function("t => document.documentElement.classList.contains(t)", arg=theme)
            _assert_theme(page, theme)
            assert page.evaluate("localStorage.getItem('theme')") == theme

        page.click(TOGGLE)  # -> dark
        page.click(TOGGLE)  # -> forest
        page.reload(wait_until="load")
        page.wait_for_selector(TOGGLE)
        _assert_theme(page, "forest")
        browser.close()
