"""Audit finding 10: CORS reflected any origin, and there was no Host check.

`ALLOWED_ORIGINS` defaulted to "*" and was combined with allow_credentials.
Starlette does not emit a literal "*" for that pair — it reflects whatever
Origin the request carried — so any page the user visited could read the whole
purchase history back off loopback. The session cookie is httponly and
samesite=lax, so writes were never reachable; this was confidentiality only.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.main import _cors_origins, _trusted_hosts


class TestCorsOriginResolution:
    def test_wildcard_reads_as_no_cors(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_ORIGINS", "*")
        assert _cors_origins() == []

    def test_wildcard_among_others_still_disables_cors(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:8000,*")
        assert _cors_origins() == []

    def test_unset_reads_as_no_cors(self, monkeypatch):
        monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
        assert _cors_origins() == []

    def test_empty_reads_as_no_cors(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_ORIGINS", "")
        assert _cors_origins() == []

    def test_explicit_origins_are_kept(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:8000, http://127.0.0.1:8000")
        assert _cors_origins() == ["http://localhost:8000", "http://127.0.0.1:8000"]


class TestNoOriginIsReflected:
    """The app under test is built with the shipped zero-config defaults."""

    def test_arbitrary_origin_is_not_reflected(self, client):
        r = client.get("/api/analytics/summary", headers={"Origin": "https://evil.example"})
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") is None, (
            "the attacker's own origin was echoed back"
        )
        assert r.headers.get("access-control-allow-credentials") is None

    def test_preflight_is_not_granted(self, client):
        r = client.options(
            "/api/analytics/summary",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert r.headers.get("access-control-allow-origin") is None


class TestTrustedHosts:
    def test_default_covers_loopback_and_the_tailnet(self, monkeypatch):
        monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
        monkeypatch.delenv("TESTING", raising=False)
        hosts = _trusted_hosts()
        assert "localhost" in hosts
        assert "127.0.0.1" in hosts
        assert "*.ts.net" in hosts, "tailscale serve is the documented remote path"
        assert "*" not in hosts

    def test_explicit_setting_wins(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_HOSTS", "grocery.example, 10.0.0.5")
        assert _trusted_hosts() == ["grocery.example", "10.0.0.5"]

    @pytest.mark.parametrize(
        ("host", "expected"),
        [
            ("localhost", 200),
            ("127.0.0.1", 200),
            ("box.tail1234.ts.net", 200),
            ("evil.example", 400),
        ],
    )
    def test_middleware_rejects_untrusted_hosts(self, host, expected):
        probe = FastAPI()
        probe.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=["localhost", "127.0.0.1", "*.ts.net"],
        )

        @probe.get("/")
        def _root():
            return {"ok": True}

        with TestClient(probe, base_url=f"http://{host}") as c:
            assert c.get("/").status_code == expected
