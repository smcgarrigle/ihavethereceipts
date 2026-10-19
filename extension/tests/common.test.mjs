import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  DEFAULT_SERVER_URL,
  buildLookupUrl,
  describeVerdict,
  formatMoney,
  formatUnitPrice,
  inferStoreFromUrl,
  matchOfflineSnapshot,
  normalizeServerUrl,
  parseJsonLdProduct,
} from "../src/common.js";

describe("normalizeServerUrl", () => {
  it("defaults to 127.0.0.1:8000 when blank", () => {
    assert.equal(normalizeServerUrl(""), DEFAULT_SERVER_URL);
    assert.equal(normalizeServerUrl("  "), DEFAULT_SERVER_URL);
  });

  it("strips trailing slashes and paths on loopback", () => {
    assert.equal(
      normalizeServerUrl("http://127.0.0.1:8000/settings"),
      "http://127.0.0.1:8000"
    );
    assert.equal(
      normalizeServerUrl("http://localhost:8000/"),
      "http://localhost:8000"
    );
  });

  it("rejects plain HTTP on non-loopback non-tailnet hosts", () => {
    assert.throws(
      () => normalizeServerUrl("http://192.168.1.50:8000"),
      /Plain http:\/\/ is only allowed/
    );
  });

  it("allows HTTPS or .ts.net hosts", () => {
    assert.equal(
      normalizeServerUrl("https://kitchen.tail1234.ts.net"),
      "https://kitchen.tail1234.ts.net"
    );
  });
});

describe("buildLookupUrl", () => {
  it("encodes query, store, size, and price parameters", () => {
    const url = buildLookupUrl("http://127.0.0.1:8000", {
      q: "Schweppes Tonic Water, 1 Liter",
      store: "Amazon Fresh",
      price: 2.29,
      limit: 3,
    });
    const parsed = new URL(url);
    assert.equal(parsed.pathname, "/api/ext/lookup");
    assert.equal(parsed.searchParams.get("q"), "Schweppes Tonic Water, 1 Liter");
    assert.equal(parsed.searchParams.get("store"), "Amazon Fresh");
    assert.equal(parsed.searchParams.get("price"), "2.29");
    assert.equal(parsed.searchParams.get("limit"), "3");
  });
});

describe("formatMoney & describeVerdict", () => {
  it("formats dollar amounts and unit prices", () => {
    assert.equal(formatMoney(2.49), "$2.49");
    assert.equal(formatUnitPrice(0.3119, "per oz"), "$0.312 per oz");
    assert.equal(formatUnitPrice(2.49, "each"), "$2.49 each");
  });

  it("describes good_deal, pricier, and incompatible comparisons", () => {
    const good = describeVerdict({
      unit_compatible: true,
      verdict: "good_deal",
      delta_pct: -47.8,
      page_unit_price: 0.3119,
      comparable_past_price: 0.598,
      basis_label: "per oz",
    });
    assert.equal(good.tone, "good");
    assert.match(good.label, /Good deal \(-47\.8%\)/);

    const incompat = describeVerdict({
      unit_compatible: false,
      verdict: null,
      basis_label: "per fl oz",
    });
    assert.equal(incompat.verdict, "incompatible");
    assert.equal(incompat.tone, "neutral");
  });
});

describe("inferStoreFromUrl", () => {
  it("identifies Amazon Fresh, Whole Foods, and Safeway URLs", () => {
    assert.equal(
      inferStoreFromUrl(
        "https://www.amazon.com/dp/B001?almBrandId=QW1hem9uIEZyZXNo",
        "Amazon.com: Schweppes : Amazon Fresh"
      ),
      "Amazon Fresh"
    );
    assert.equal(
      inferStoreFromUrl(
        "https://www.amazon.com/dp/B002",
        "Whole Foods Market: Organic Baby Spinach"
      ),
      "Whole Foods Market"
    );
    assert.equal(
      inferStoreFromUrl("https://www.safeway.com/shop/product-details.960012345.html"),
      "Safeway"
    );
    assert.equal(inferStoreFromUrl("https://example.com/item"), null);
  });
});

describe("parseJsonLdProduct", () => {
  it("extracts Product name, offer price, and gtin13 from JSON-LD", () => {
    const ld = JSON.stringify({
      "@context": "https://schema.org",
      "@type": "Product",
      name: "Signature SELECT Grade AA Large Eggs - 18 Count",
      gtin13: "0002113001234",
      offers: {
        "@type": "Offer",
        price: "4.49",
      },
    });
    const parsed = parseJsonLdProduct([ld]);
    assert.deepEqual(parsed, {
      title: "Signature SELECT Grade AA Large Eggs - 18 Count",
      price: 4.49,
      gtin: "0002113001234",
    });
  });
});

describe("matchOfflineSnapshot", () => {
  const sampleSnapshot = [
    {
      item_id: 101,
      name: "Schweppes Tonic Water",
      cleaned_name: "schweppes tonic water",
      gtin: "0007800001185",
      unit: "fl oz",
      basis: "fl oz",
      basis_label: "per fl oz",
      comparable_avg: 0.058,
      last_paid: {
        price: 2.49,
        unit_price: 0.0737,
        basis: "fl oz",
        basis_label: "per fl oz",
        store: "Amazon Fresh",
        date: "2026-09-20",
      },
      all_stores: {
        min_price: 1.49,
        max_price: 2.49,
        avg_price: 1.99,
        best_store: "Total Wine",
        best_price: 1.49,
        best_date: "2026-08-10",
        total_purchases: 2,
      },
      stores: [
        {
          store: "Amazon Fresh",
          last_price: 2.49,
          last_unit_price: 0.0737,
          last_date: "2026-09-20",
          min_price: 2.49,
          avg_price: 2.49,
          count: 1,
        },
        {
          store: "Total Wine",
          last_price: 1.49,
          last_unit_price: 0.0441,
          last_date: "2026-08-10",
          min_price: 1.49,
          avg_price: 1.49,
          count: 1,
        },
      ],
    },
    {
      item_id: 202,
      name: "Water",
      cleaned_name: "water",
      gtin: null,
      unit: null,
      basis: "each",
      basis_label: "each",
      comparable_avg: 0.99,
      last_paid: {
        price: 0.99,
        unit_price: 0.99,
        basis: "each",
        basis_label: "each",
        store: "Safeway",
        date: "2026-08-01",
      },
      all_stores: {
        min_price: 0.99,
        max_price: 0.99,
        avg_price: 0.99,
        best_store: "Safeway",
        best_price: 0.99,
        best_date: "2026-08-01",
        total_purchases: 1,
      },
      stores: [],
    },
    {
      item_id: 303,
      name: "Organic Blueberry Pint",
      cleaned_name: "organic blueberry",
      gtin: null,
      unit: null,
      basis: "each",
      basis_label: "each",
      comparable_avg: 5.99,
      last_paid: {
        price: 5.99,
        unit_price: 5.99,
        basis: "each",
        basis_label: "each",
        store: "Whole Foods Market",
        date: "2024-05-26",
      },
      all_stores: {
        min_price: 5.99,
        max_price: 5.99,
        avg_price: 5.99,
        best_store: "Whole Foods Market",
        best_price: 5.99,
        best_date: "2024-05-26",
        total_purchases: 1,
      },
      stores: [],
    },
  ];

  it("matches retail title offline, populates at_this_store & comparison, and rejects generic or qualifier-only decoys", () => {
    const res = matchOfflineSnapshot(sampleSnapshot, {
      q: "Schweppes Tonic Water, 1 Liter Bottle",
      store: "Amazon Fresh",
      price: 1.49,
    });
    assert.equal(res.matches.length, 1);
    const top = res.matches[0];
    assert.equal(top.item_id, 101);
    assert.ok(top.confidence >= 90);
    assert.equal(top.at_this_store.store, "Amazon Fresh");
    assert.equal(top.all_stores.best_store, "Total Wine");
    assert.equal(top.comparison.unit_compatible, true);
    assert.equal(top.comparison.verdict, "good_deal");

    const spinachRes = matchOfflineSnapshot(sampleSnapshot, {
      q: "Organic Baby Spinach, 16 Ounce",
      store: "Amazon Fresh",
      price: 4.99,
    });
    assert.equal(spinachRes.matches.length, 0);
  });

  it("matches by GTIN barcode even when title differs", () => {
    const res = matchOfflineSnapshot(sampleSnapshot, {
      q: "Unrelated Marketing Name",
      gtin: "7800001185",
    });
    assert.equal(res.matches.length, 1);
    assert.equal(res.matches[0].item_id, 101);
    assert.equal(res.matches[0].matched_by, "gtin");
    assert.equal(res.matches[0].confidence, 100);
  });
});
