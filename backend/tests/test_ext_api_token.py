"""TruePriceMemory browser extension: token auth and the /api/ext/ping endpoint.

The app has no login and CORS is deliberately off (see test_cors_and_host.py),
so the extension's bearer token is the only thing standing between a purchase
history and any local process or web page that can reach loopback. These tests
pin the properties that make it a real gate: no token / bad token / revoked
token are all the same 401, the secret is never stored, and issuing or showing
a token never leaks it again.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from app.models.api_token import ApiToken
from app.services import ext_tokens


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _issue(client, name: str = "My laptop") -> str:
    """Create a token through the real Settings endpoint and return the secret."""
    r = client.post("/settings/extension/tokens", data={"name": name})
    assert r.status_code == 200, r.text
    # The secret is rendered exactly once inside <code id="new-ext-token">.
    marker = 'id="new-ext-token">'
    assert marker in r.text, "a freshly created token must be shown to the user"
    start = r.text.index(marker) + len(marker)
    return str(r.text[start : r.text.index("<", start)]).strip()


class TestPingRequiresAToken:
    def test_missing_header_is_401(self, client):
        r = client.get("/api/ext/ping")
        assert r.status_code == 401
        assert r.headers.get("www-authenticate") == "Bearer"

    def test_unknown_token_is_401(self, client):
        r = client.get("/api/ext/ping", headers=_bearer("tpm_not-a-real-token"))
        assert r.status_code == 401

    @pytest.mark.parametrize("header", ["Basic abc", "Bearer", "Bearer ", "tpm_abc", ""])
    def test_malformed_authorization_is_401(self, client, header):
        r = client.get("/api/ext/ping", headers={"Authorization": header})
        assert r.status_code == 401

    def test_failures_are_indistinguishable(self, client):
        """Missing, unknown and revoked must not tell a caller which it was."""
        missing = client.get("/api/ext/ping")
        unknown = client.get("/api/ext/ping", headers=_bearer("tpm_nope"))
        assert missing.json() == unknown.json()

    def test_valid_token_is_accepted(self, client):
        token = _issue(client)
        r = client.get("/api/ext/ping", headers=_bearer(token))
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["app"] == "TruePriceMemory"
        assert "version" in body

    def test_ping_is_not_cacheable(self, client):
        token = _issue(client)
        r = client.get("/api/ext/ping", headers=_bearer(token))
        assert "no-store" in r.headers.get("cache-control", "")


class TestTokensAreStoredSafely:
    def test_secret_is_never_stored(self, client, db):
        token = _issue(client)
        row = db.query(ApiToken).one()
        assert token.startswith("tpm_")
        assert token not in {row.token_hash, row.name, row.token_prefix}
        assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()

    def test_tokens_are_long_and_unique(self, client):
        a, b = _issue(client, "a"), _issue(client, "b")
        assert a != b
        assert len(a) >= 40

    def test_secret_is_not_repeated_on_later_page_loads(self, client):
        token = _issue(client)
        page = client.get("/settings")
        assert page.status_code == 200
        assert token not in page.text
        assert "My laptop" in page.text, "the token's name is listed"

    def test_name_is_escaped(self, client):
        _issue(client, "<script>alert(1)</script>")
        page = client.get("/settings")
        assert "<script>alert(1)</script>" not in page.text

    def test_blank_name_gets_a_default(self, client, db):
        _issue(client, "   ")
        assert db.query(ApiToken).one().name == "Browser extension"

    def test_overlong_name_is_trimmed(self, client, db):
        _issue(client, "x" * 500)
        assert len(db.query(ApiToken).one().name) <= 60


class TestRevocation:
    def test_revoked_token_stops_working(self, client, db):
        token = _issue(client)
        token_id = db.query(ApiToken).one().id
        assert client.get("/api/ext/ping", headers=_bearer(token)).status_code == 200

        r = client.delete(f"/settings/extension/tokens/{token_id}")
        assert r.status_code == 200
        assert client.get("/api/ext/ping", headers=_bearer(token)).status_code == 401

    def test_revoking_one_token_leaves_the_others(self, client, db):
        keep, drop = _issue(client, "keep"), _issue(client, "drop")
        drop_id = db.query(ApiToken).filter(ApiToken.name == "drop").one().id
        client.delete(f"/settings/extension/tokens/{drop_id}")
        assert client.get("/api/ext/ping", headers=_bearer(keep)).status_code == 200
        assert client.get("/api/ext/ping", headers=_bearer(drop)).status_code == 401

    def test_revoking_a_missing_token_is_harmless(self, client):
        assert client.delete("/settings/extension/tokens/9999").status_code == 200


class TestUsageTracking:
    def test_last_used_is_recorded(self, client, db):
        token = _issue(client)
        assert db.query(ApiToken).one().last_used_at is None
        client.get("/api/ext/ping", headers=_bearer(token))
        db.expire_all()
        assert db.query(ApiToken).one().last_used_at is not None

    def test_last_used_writes_are_throttled(self, client, db):
        """A chatty content script must not turn every GET into a SQLite write."""
        token = _issue(client)
        client.get("/api/ext/ping", headers=_bearer(token))
        db.expire_all()
        first = db.query(ApiToken).one().last_used_at

        client.get("/api/ext/ping", headers=_bearer(token))
        db.expire_all()
        assert db.query(ApiToken).one().last_used_at == first

    def test_stale_last_used_is_refreshed(self, client, db):
        token = _issue(client)
        row = db.query(ApiToken).one()
        old = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        row.last_used_at = old
        db.commit()
        client.get("/api/ext/ping", headers=_bearer(token))
        db.expire_all()
        assert db.query(ApiToken).one().last_used_at > old


class TestLimits:
    def test_active_tokens_are_capped(self, client):
        for i in range(ext_tokens.MAX_ACTIVE_TOKENS):
            _issue(client, f"t{i}")
        r = client.post("/settings/extension/tokens", data={"name": "one too many"})
        assert r.status_code == 200
        assert 'id="new-ext-token"' not in r.text
        assert "Revoke" in r.text, "the user is told to revoke one first"

    def test_revoked_tokens_do_not_count_toward_the_cap(self, client, db):
        for i in range(ext_tokens.MAX_ACTIVE_TOKENS):
            _issue(client, f"t{i}")
        client.delete(f"/settings/extension/tokens/{db.query(ApiToken).first().id}")
        assert _issue(client, "fits again")


class TestNoCorsIsNeeded:
    """An extension with host_permissions is not subject to CORS, so none is opened."""

    def test_foreign_origin_is_not_reflected_on_ext_routes(self, client):
        token = _issue(client)
        r = client.get(
            "/api/ext/ping",
            headers={**_bearer(token), "Origin": "https://evil.example"},
        )
        assert r.headers.get("access-control-allow-origin") is None

    def test_preflight_is_not_granted(self, client):
        r = client.options(
            "/api/ext/ping",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert r.headers.get("access-control-allow-origin") is None


class TestSettingsPageSection:
    def test_section_is_present_and_named(self, client):
        page = client.get("/settings")
        assert page.status_code == 200
        assert "TruePriceMemory" in page.text
        assert "/settings/extension/tokens" in page.text
