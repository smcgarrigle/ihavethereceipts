"""Audit finding 12: a missing template turned any unknown item id into a 500.

`pages.py` rendered "pages/404.html", which did not exist and was the only
reference to it anywhere, so `GET /items/9999/insights` raised TemplateNotFound.
There was no exception handler either, so `GET /nope` and
`GET /receipts/9999/review` rendered raw JSON in the browser.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from app.api.templates import templates

APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"

BROWSER = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


def _template_names_in_source() -> set[str]:
    """Every string literal handed to a TemplateResponse call in app/."""
    names: set[str] = set()
    for path in APP_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            attr = func.attr if isinstance(func, ast.Attribute) else None
            if attr != "TemplateResponse":
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if arg.value.endswith(".html"):
                        names.add(arg.value)
    return names


def test_every_template_name_in_the_source_resolves():
    """The ten-line test that would have caught this finding."""
    names = _template_names_in_source()
    assert names, "no TemplateResponse calls found — has the scan broken?"

    missing = []
    for name in sorted(names):
        try:
            templates.get_template(name)
        except Exception as exc:  # noqa: BLE001 - report every one, not the first
            missing.append(f"{name}: {type(exc).__name__}")
    assert not missing, "templates referenced in app/ that do not resolve: " + ", ".join(missing)


@pytest.mark.parametrize("name", ["pages/404.html", "pages/403.html"])
def test_error_templates_exist(name):
    assert templates.get_template(name)


class TestBrowserGetsAPage:
    @pytest.mark.parametrize("url", ["/nope", "/items/9999/insights", "/receipts/9999/review"])
    def test_unknown_urls_render_the_404_page(self, client, url):
        r = client.get(url, headers=BROWSER)
        assert r.status_code == 404
        assert r.headers["content-type"].startswith("text/html")
        assert "Clean-up on aisle 404" in r.text
        assert "crashed-cart-title" in r.text, "the illustration is missing"

    def test_item_insights_no_longer_raises(self, client):
        """This one used to be a bare 500 from TemplateNotFound."""
        r = client.get("/items/9999/insights", headers=BROWSER)
        assert r.status_code == 404

    def test_specific_detail_is_shown_alongside_the_blurb(self, client):
        r = client.get("/items/9999/insights", headers=BROWSER)
        assert "No item with that id is on the shelves." in r.text
        assert "we checked the other back" in r.text, "the blurb was replaced"

    def test_generic_reason_phrase_is_not_echoed(self, client):
        """ "Not Found" as a message adds nothing the page does not say better."""
        r = client.get("/nope", headers=BROWSER)
        assert 'text-textSubtle">Not Found' not in r.text


class TestScriptsStillGetJson:
    def test_api_clients_return_json(self, client):
        """An API caller sends */* (curl, fetch) and keeps its JSON."""
        r = client.get("/api/receipts/9999/review-data", headers={"Accept": "*/*"})
        assert r.status_code == 404
        assert r.headers["content-type"].startswith("application/json")

    def test_navigating_to_an_api_url_in_a_browser_gets_a_page(self, client):
        """Negotiation is on Accept, not on the path.

        That is deliberate: a plain form post lands on an /api/ route as often
        as not, and the person who submitted it is looking at a browser window
        either way.
        """
        r = client.get("/api/receipts/9999/review-data", headers=BROWSER)
        assert r.status_code == 404
        assert r.headers["content-type"].startswith("text/html")

    def test_htmx_requests_return_json(self, client):
        r = client.get("/nope", headers={**BROWSER, "HX-Request": "true"})
        assert r.status_code == 404
        assert r.headers["content-type"].startswith("application/json")

    def test_a_plain_client_returns_json(self, client):
        r = client.get("/nope", headers={"Accept": "*/*"})
        assert r.status_code == 404
        assert r.headers["content-type"].startswith("application/json")


class TestCsrfFailureIsAPage:
    """CSRF returns its 403 straight from middleware, bypassing the handler.

    The middleware skips itself entirely when TESTING=1, so these turn that off
    for the duration of the request — it re-reads the variable each time.
    """

    @pytest.fixture(autouse=True)
    def csrf_on(self, monkeypatch):
        monkeypatch.setenv("TESTING", "0")

    def test_form_post_gets_the_403_page(self, client):
        r = client.post("/nope", data={"x": "1"}, headers=BROWSER)
        assert r.status_code == 403
        assert r.headers["content-type"].startswith("text/html")
        assert "Staff only past this point" in r.text
        assert "roped off" in r.text, "the blurb was replaced by the CSRF detail"
        assert "crashed-cart-title" in r.text

    def test_api_client_still_gets_csrf_json(self, client):
        r = client.post("/api/receipts/upload", headers={"Accept": "*/*"})
        assert r.status_code == 403
        assert r.headers["content-type"].startswith("application/json")
        assert "CSRF" in r.json()["detail"]
