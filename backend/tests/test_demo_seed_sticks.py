"""Audit finding 13: cleared demo data came back on the next dashboard visit.

Seeding was gated on `receipt_count == 0` alone with no "onboarding complete"
marker, so clearing the demo lasted exactly one request — the next `GET /` put
the three fictional receipts straight back. It also meant the genuinely-empty
dashboard state was unreachable, and therefore untested.
"""

from __future__ import annotations

import json

import pytest

from app.api import settings_router
from app.api.settings_router import _load_feature_flags
from app.models import Receipt, Store
from app.services.onboarding import (
    ONBOARDING_FLAG,
    clear_demo_data,
    onboarding_is_complete,
    populate_demo_data,
)

DEMO_STORES = ["Trader Joe's", "Safeway", "Costco"]


def _count(db) -> int:
    db.expire_all()
    return int(db.query(Receipt).count())


class TestTheDemoStaysCleared:
    def test_a_fresh_install_still_gets_the_demo(self, client, db):
        assert _count(db) == 0
        client.get("/")
        assert _count(db) == 3, "a first-run visitor should still see the demo"

    def test_clearing_survives_the_next_visit(self, client, db):
        client.get("/")
        assert _count(db) == 3

        assert client.post("/api/onboarding/clear-demo").status_code == 200
        assert _count(db) == 0

        client.get("/")
        assert _count(db) == 0, "the demo came back on the next dashboard visit"

    def test_it_stays_cleared_across_many_visits(self, client, db):
        client.get("/")
        client.post("/api/onboarding/clear-demo")
        for _ in range(3):
            client.get("/")
        assert _count(db) == 0


class TestTheEmptyDashboard:
    """Previously unreachable: something always re-seeded before it rendered."""

    def test_it_renders(self, client, db):
        client.get("/")
        client.post("/api/onboarding/clear-demo")

        r = client.get("/")
        assert r.status_code == 200
        assert _count(db) == 0

    def test_it_does_not_advertise_demo_stores(self, client):
        client.get("/")
        client.post("/api/onboarding/clear-demo")

        body = client.get("/").text
        for store in DEMO_STORES:
            assert store not in body, f"{store} survived the clear"


class TestTheFlag:
    def test_it_is_persisted_where_the_other_flags_live(self, client):
        client.get("/")
        client.post("/api/onboarding/clear-demo")

        assert onboarding_is_complete() is True
        # Read the attribute, not a value bound at import: conftest redirects
        # it per test so the repo's tracked flags file is never written.
        written = json.loads(settings_router.FEATURE_FLAGS_PATH.read_text())
        assert written[ONBOARDING_FLAG] is True

    def test_it_leaves_the_other_flags_alone(self, client):
        from app.api.settings_router import _save_feature_flags

        _save_feature_flags({"usda_lookup_enabled": False, "protein_roi_target": 0.31})

        client.get("/")
        client.post("/api/onboarding/clear-demo")

        flags = _load_feature_flags()
        assert flags["usda_lookup_enabled"] is False
        assert flags["protein_roi_target"] == 0.31
        assert flags[ONBOARDING_FLAG] is True

    def test_a_failed_clear_does_not_set_it(self, db, monkeypatch):
        """A flag set beside a failed delete would strand the user.

        The demo would be gone from the dashboard and unrecoverable, while the
        rows it was meant to delete were still in the database.
        """
        populate_demo_data(db)
        assert _count(db) == 3

        def boom():
            raise RuntimeError("commit failed")

        monkeypatch.setattr(db, "commit", boom)

        assert clear_demo_data(db) is False
        assert onboarding_is_complete() is False, "the flag was set despite the failure"

    def test_unset_by_default(self):
        assert onboarding_is_complete() is False


class TestRealDataIsNeverTouched:
    @pytest.mark.parametrize("cleared", [False, True])
    def test_a_real_receipt_prevents_seeding(self, client, db, cleared):
        store = Store(name="A Real Shop")
        db.add(store)
        db.commit()
        db.add(Receipt(store_id=store.id, total_amount=12.0, status="completed"))
        db.commit()

        if cleared:
            client.post("/api/onboarding/clear-demo")

        client.get("/")
        assert _count(db) == 1
        assert db.query(Store).filter(Store.name.in_(DEMO_STORES)).count() == 0
