"""TruePriceMemory browser extension: retail title cleaning, matching, and /api/ext/lookup.

Covers PR 2 of the extension plan:
1. Retail title cleaning (Amazon Fresh and Safeway titles with pack/size/brand noise).
2. Fuzzy matching that handles verbose retail titles without falling for the
   single-word subset trap (e.g., "Schweppes Tonic Water" must not match a generic
   "WATER" item at 100%).
3. Store-context ranking boost (reusing STORE_CONTEXT_RANK_BOOST without inflating
   reported confidence or bypassing the threshold).
4. Exact GTIN barcode matching when a page exposes JSON-LD gtin13/gtin12.
5. Size-aware unit price comparison (converting compatible units like 1 L -> oz
   or 6-pack -> per unit, and refusing to compare incompatible units like lb vs ct).
6. Data minimisation (no image_path, ocr_data, or filesystem paths in responses)
   and per-token rate limiting.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.models import Category, Item, Receipt, ReceiptItem, Store
from app.services import ext_matcher, ext_tokens


def _auth_headers(db) -> dict[str, str]:
    created = ext_tokens.create_token(db, "test-ext")
    assert created is not None
    _row, secret = created
    return {"Authorization": f"Bearer {secret}"}


def _seed_store(db, name: str) -> Store:
    existing: Store | None = db.query(Store).filter(Store.name == name).first()
    if existing is not None:
        return existing
    s = Store(name=name)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _seed_item(db, name: str, *, gtin: str | None = None) -> Item:
    cat = db.query(Category).filter(Category.name == "Beverages").first()
    if not cat:
        cat = Category(name="Beverages")
        db.add(cat)
        db.commit()
    item = Item(
        name=name,
        normalized_name=name.lower().strip(),
        category_id=cat.id,
        gtin=gtin,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _seed_purchase(
    db,
    store: Store,
    item: Item,
    *,
    price: float,
    quantity: float = 1.0,
    weight: float | None = None,
    unit_type: str | None = None,
    unit_price: float | None = None,
    date: datetime | None = None,
) -> ReceiptItem:
    r = Receipt(
        store_id=store.id,
        status="completed",
        purchase_date=date or datetime(2026, 9, 15),
        total_amount=round(price * quantity, 2),
        image_path="/secret/path/receipt.pdf",
        ocr_data='{"raw": "secret ocr payload"}',
    )
    db.add(r)
    db.commit()
    ri = ReceiptItem(
        receipt_id=r.id,
        item_id=item.id,
        quantity=quantity,
        price=price,
        weight=weight,
        unit_type=unit_type,
        unit_price=unit_price if unit_price is not None else price,
    )
    db.add(ri)
    db.commit()
    return ri


class TestCleanRetailTitle:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (
                "Schweppes Tonic Water, 1 Liter Bottle (Pack of 6)",
                "schweppes tonic water",
            ),
            (
                "Signature SELECT Grade AA Large Eggs - 18 Count",
                "grade aa large eggs",
            ),
            (
                "365 by Whole Foods Market, Organic Baby Spinach, 16 Ounce",
                "organic baby spinach",
            ),
            (
                "Amazon Fresh Organic Honeycrisp Apples, 2 lb Bag",
                "organic honeycrisp apples",
            ),
            (
                "Oikos Triple Zero Vanilla Greek Yogurt, 4 Ct, 5.3 oz Cups",
                "oikos triple zero vanilla greek yogurt",
            ),
            (
                "Kerrygold Pure Irish Butter, Salted, 8 oz",
                "kerrygold pure irish butter salted",
            ),
        ],
    )
    def test_strips_size_pack_and_store_brand_boilerplate(self, raw: str, expected: str):
        assert ext_matcher.clean_retail_title(raw) == expected


class TestParseRetailSize:
    def test_parses_single_liter_bottle(self):
        parsed = ext_matcher.parse_retail_size("Schweppes Tonic Water, 1 Liter Bottle")
        assert parsed is not None
        assert parsed.unit == "l"
        assert parsed.amount == pytest.approx(1.0)
        assert parsed.total_oz == pytest.approx(33.814, rel=1e-2)

    def test_parses_multipack_fluid_ounces(self):
        parsed = ext_matcher.parse_retail_size("Schweppes Tonic Water, 10 Fl Oz (Pack of 6)")
        assert parsed is not None
        assert parsed.pack_count == 6
        assert parsed.total_oz == pytest.approx(60.0)

    def test_parses_count_only(self):
        parsed = ext_matcher.parse_retail_size("Large Eggs - 18 Count")
        assert parsed is not None
        assert parsed.unit == "ct"
        assert parsed.amount == pytest.approx(18.0)
        assert parsed.total_count == pytest.approx(18.0)


class TestLookupEndpoint:
    def test_requires_auth_token(self, client):
        r = client.get("/api/ext/lookup", params={"q": "tonic water"})
        assert r.status_code == 401

    def test_tonic_water_scenario_across_stores(self, client, db):
        """User is on Amazon Fresh looking at Schweppes Tonic Water for $2.29
        and remembers paying less at Total Wine."""
        headers = _auth_headers(db)
        total_wine = _seed_store(db, "Total Wine")
        amazon_fresh = _seed_store(db, "Amazon Fresh")
        safeway = _seed_store(db, "Safeway")

        tonic = _seed_item(db, "Schweppes Tonic Water")
        # Decoy generic item that must NOT outrank or falsely score 100
        water = _seed_item(db, "Water")
        _seed_purchase(db, safeway, water, price=0.99, date=datetime(2026, 8, 1))

        _seed_purchase(
            db,
            total_wine,
            tonic,
            price=1.49,
            weight=33.8,
            unit_type="fl oz",
            date=datetime(2026, 8, 10),
        )
        _seed_purchase(
            db,
            amazon_fresh,
            tonic,
            price=2.49,
            weight=33.8,
            unit_type="fl oz",
            date=datetime(2026, 9, 20),
        )

        r = client.get(
            "/api/ext/lookup",
            params={
                "q": "Schweppes Tonic Water, 1 Liter Bottle",
                "store": "Amazon Fresh",
                "price": 2.29,
            },
            headers=headers,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["store"] == "Amazon Fresh"
        assert len(data["matches"]) >= 1

        top = data["matches"][0]
        assert top["item_id"] == tonic.id
        assert top["name"] == "Schweppes Tonic Water"
        assert top["confidence"] >= 90

        # Generic "Water" must not be matched to "Schweppes Tonic Water"
        matched_ids = [m["item_id"] for m in data["matches"]]
        assert water.id not in matched_ids

        # Last paid is the most recent purchase (Amazon Fresh on 2026-09-20)
        assert top["last_paid"]["store"] == "Amazon Fresh"
        assert top["last_paid"]["price"] == pytest.approx(2.49)
        assert top["last_paid"]["date"] == "2026-09-20"

        # Store-specific stats for Amazon Fresh
        assert top["at_this_store"] is not None
        assert top["at_this_store"]["store"] == "Amazon Fresh"
        assert top["at_this_store"]["last_price"] == pytest.approx(2.49)
        assert top["at_this_store"]["count"] == 1

        # All-stores best price points to Total Wine at $1.49
        assert top["all_stores"]["best_store"] == "Total Wine"
        assert top["all_stores"]["best_price"] == pytest.approx(1.49)
        assert top["all_stores"]["min_price"] == pytest.approx(1.49)
        assert top["all_stores"]["total_purchases"] == 2

        # History is ordered newest first
        assert [h["store"] for h in top["history"]] == ["Amazon Fresh", "Total Wine"]

    def test_selected_text_lookup_matches_brand_item(self, client, db):
        """Highlighting just 'tonic water' on a page still finds 'Schweppes Tonic Water'."""
        headers = _auth_headers(db)
        total_wine = _seed_store(db, "Total Wine")
        tonic = _seed_item(db, "Schweppes Tonic Water")
        _seed_purchase(db, total_wine, tonic, price=1.49)

        r = client.get(
            "/api/ext/lookup",
            params={"q": "tonic water"},
            headers=headers,
        )
        assert r.status_code == 200
        matches = r.json()["matches"]
        assert len(matches) == 1
        assert matches[0]["item_id"] == tonic.id
        assert matches[0]["confidence"] >= 85

    def test_gtin_exact_match_wins_even_when_title_differs(self, client, db):
        headers = _auth_headers(db)
        safeway = _seed_store(db, "Safeway")
        item = _seed_item(db, "SW TONIC WTR", gtin="0007800001185")
        _seed_purchase(db, safeway, item, price=1.79)

        r = client.get(
            "/api/ext/lookup",
            params={"q": "Completely Different Marketing Title", "gtin": "7800001185"},
            headers=headers,
        )
        assert r.status_code == 200
        matches = r.json()["matches"]
        assert len(matches) == 1
        assert matches[0]["item_id"] == item.id
        assert matches[0]["matched_by"] == "gtin"
        assert matches[0]["confidence"] == 100

    def test_store_context_boosts_ranking_without_inflating_confidence(self, client, db):
        headers = _auth_headers(db)
        safeway = _seed_store(db, "Safeway")
        costco = _seed_store(db, "Costco")

        item_safeway = _seed_item(db, "Organic Fuji Apples")
        item_costco = _seed_item(db, "Organic Fuji Apple")
        _seed_purchase(db, safeway, item_safeway, price=3.99)
        _seed_purchase(db, costco, item_costco, price=8.99)

        r = client.get(
            "/api/ext/lookup",
            params={"q": "Organic Fuji Apple", "store": "Safeway"},
            headers=headers,
        )
        assert r.status_code == 200
        matches = r.json()["matches"]
        assert len(matches) == 2
        # Safeway item ranks first thanks to store boost, even though its raw text
        # similarity is slightly lower than the exact singular match.
        assert matches[0]["item_id"] == item_safeway.id
        assert matches[0]["confidence"] <= 100
        assert matches[0]["confidence"] < matches[1]["confidence"]

    def test_unit_compatible_comparison_and_incompatible_guard(self, client, db):
        """A 6-pack on the page is compared per-oz against a single bottle when
        both have fluid-ounce sizes, and refused when units are incompatible."""
        headers = _auth_headers(db)
        total_wine = _seed_store(db, "Total Wine")
        tonic = _seed_item(db, "Schweppes Tonic Water")
        # Paid $1.69 for a 33.8 fl oz (1L) bottle -> $0.05/fl oz
        _seed_purchase(
            db,
            total_wine,
            tonic,
            price=1.69,
            weight=33.814,
            unit_type="fl oz",
        )

        # Page shows a 6-pack of 10 fl oz (60 fl oz total) for $6.00 -> $0.10/fl oz (pricier!)
        r = client.get(
            "/api/ext/lookup",
            params={
                "q": "Schweppes Tonic Water",
                "size": "10 fl oz (Pack of 6)",
                "price": 6.00,
            },
            headers=headers,
        )
        assert r.status_code == 200
        comp = r.json()["matches"][0]["comparison"]
        assert comp is not None
        assert comp["unit_compatible"] is True
        assert comp["page_unit_price"] == pytest.approx(0.10, abs=1e-2)
        assert comp["verdict"] == "pricier"

        # Now page has an incompatible count-only size ("6 count") with no volume:
        # must NOT compare a 6-pack price against a per-fl-oz basis.
        r_incompat = client.get(
            "/api/ext/lookup",
            params={
                "q": "Schweppes Tonic Water",
                "size": "6 count",
                "price": 6.00,
            },
            headers=headers,
        )
        comp_incompat = r_incompat.json()["matches"][0]["comparison"]
        assert comp_incompat is not None
        assert comp_incompat["unit_compatible"] is False
        assert comp_incompat["verdict"] is None

    def test_unbought_product_returns_empty_matches(self, client, db):
        headers = _auth_headers(db)
        store = _seed_store(db, "Safeway")
        item = _seed_item(db, "Schweppes Tonic Water")
        _seed_purchase(db, store, item, price=1.99)

        r = client.get(
            "/api/ext/lookup",
            params={"q": "Duracell AA Alkaline Batteries 24 Pack"},
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["matches"] == []

    def test_response_does_not_leak_sensitive_receipt_fields(self, client, db):
        headers = _auth_headers(db)
        store = _seed_store(db, "Safeway")
        item = _seed_item(db, "Schweppes Tonic Water")
        _seed_purchase(db, store, item, price=1.99)

        r = client.get(
            "/api/ext/lookup",
            params={"q": "Schweppes Tonic Water"},
            headers=headers,
        )
        assert r.status_code == 200
        raw_text = r.text
        assert "/secret/path" not in raw_text
        assert "secret ocr payload" not in raw_text
        assert "image_path" not in raw_text
        assert "ocr_data" not in raw_text

    def test_qualifier_only_overlap_is_rejected(self, client, db):
        """'Organic Baby Spinach' and 'Organic Blueberry Pint' share only 'organic'
        and must not match each other."""
        headers = _auth_headers(db)
        wfm = _seed_store(db, "Whole Foods Market")
        spinach = _seed_item(db, "365 by Whole Foods Market Organic Baby Spinach Salad, 5 OZ")
        blueberry = _seed_item(db, "Organic Blueberry Pint")
        _seed_purchase(db, wfm, spinach, price=2.99, weight=5.0, unit_type="oz")
        _seed_purchase(db, wfm, blueberry, price=5.99)

        r = client.get(
            "/api/ext/lookup",
            params={"q": "Organic Baby Spinach, 16 Ounce", "store": "Amazon Fresh", "price": 4.99},
            headers=headers,
        )
        assert r.status_code == 200
        matched_ids = [m["item_id"] for m in r.json()["matches"]]
        assert matched_ids == [spinach.id]

    def test_per_token_rate_limit_blocks_runaway_caller(self, client, db, monkeypatch):
        from app.api import ext_router

        monkeypatch.setattr(ext_router, "EXT_RATE_LIMIT", 3)
        headers = _auth_headers(db)
        for _ in range(3):
            assert (
                client.get("/api/ext/lookup", params={"q": "milk"}, headers=headers).status_code
                == 200
            )
        blocked = client.get("/api/ext/lookup", params={"q": "milk"}, headers=headers)
        assert blocked.status_code == 429
