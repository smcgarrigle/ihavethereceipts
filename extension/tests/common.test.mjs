import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  DEFAULT_SERVER_URL,
  buildLookupUrl,
  describeVerdict,
  formatMoney,
  formatUnitPrice,
  inferStoreFromUrl,
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
