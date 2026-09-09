"""The static-demo build must use a Host the app actually answers to.

PR #10 added ``TrustedHostMiddleware`` to close the DNS-rebinding path around
the loopback bind. ``build_static_demo.py`` drives the app with a ``TestClient``,
which defaults to ``http://testserver`` — not a trusted host — so every request
the crawl made came back ``400 Invalid host header``. The builder saved zero
responses, reported success, and eighteen consecutive Pages deploys went red at
the workflow's verify step instead of at the cause.

The suite could not see it: ``conftest`` sets ``TESTING``, which widens the
allowlist to ``"*"``. These tests therefore evaluate the allowlist with
``TESTING`` cleared, the way the build actually runs.
"""

import importlib.util
from pathlib import Path
from urllib.parse import urlparse

import pytest

from app.main import _trusted_hosts

BUILDER = Path(__file__).resolve().parent.parent / "scripts" / "build_static_demo.py"


def _builder_base_url() -> str:
    """Read CLIENT_BASE_URL without importing the module's heavy dependencies."""
    import ast

    for node in ast.parse(BUILDER.read_text()).body:
        if (
            isinstance(node, ast.Assign)
            and getattr(node.targets[0], "id", None) == "CLIENT_BASE_URL"
        ):
            return str(ast.literal_eval(node.value))
    raise AssertionError("build_static_demo.py no longer defines CLIENT_BASE_URL")


@pytest.fixture
def production_hosts(monkeypatch):
    """The allowlist as the Pages build sees it — no TESTING, no ALLOWED_HOSTS."""
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    return _trusted_hosts()


def test_builder_uses_a_host_the_app_trusts(production_hosts):
    host = urlparse(_builder_base_url()).hostname
    assert host in production_hosts, (
        f"build_static_demo.py crawls as Host {host!r}, which is not in "
        f"{production_hosts}. Every request will come back 400 and the "
        "snapshot will be empty — the Pages deploy fails."
    )


def test_testclient_default_host_is_not_trusted(production_hosts):
    """The negative control: this is why the constant has to exist.

    If ``testserver`` ever became trusted this guard would pass vacuously, so
    assert the thing that made the builder's default wrong in the first place.
    """
    assert "testserver" not in production_hosts


def test_testing_widens_the_allowlist(monkeypatch):
    """Documents why the suite missed this, so the next reader does not re-derive it."""
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    monkeypatch.setenv("TESTING", "1")
    assert _trusted_hosts() == ["*"]


def test_builder_reports_failure_on_an_empty_snapshot():
    """A snapshot with nothing in it must exit non-zero, not print a tick."""
    source = BUILDER.read_text()
    assert "if saved == 0:" in source, (
        "build_static_demo.py no longer fails on an empty snapshot; a build that "
        "captured nothing would report success again."
    )


def test_builder_module_imports():
    """Guards the constant and the module against a syntax-level mistake."""
    spec = importlib.util.spec_from_file_location("build_static_demo_under_test", BUILDER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.CLIENT_BASE_URL == _builder_base_url()
