import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  extractAmazonProduct,
  extractProductFromPage,
  extractSafewayProduct,
  parsePriceText,
} from "../src/content/extractors.js";

/**
 * Minimal DOM stub so we can test retailer HTML fixtures in Node with zero npm deps.
 */
function makeDoc({
  title = "",
  jsonLd = [],
  selectors = {},
  metas = {},
} = {}) {
  return {
    title,
    querySelector(sel) {
      if (sel in selectors) {
        const val = selectors[sel];
        if (typeof val === "string") {
          return {
            textContent: val,
            getAttribute: (attr) => (attr === "content" ? val : null),
          };
        }
        return val;
      }
      if (sel.startsWith("meta[")) {
        const key = Object.keys(metas).find((k) => sel.includes(k));
        if (key) {
          return {
            getAttribute: (attr) => (attr === "content" ? metas[key] : null),
            textContent: "",
          };
        }
      }
      return null;
    },
    querySelectorAll(sel) {
      if (sel === 'script[type="application/ld+json"]') {
        return jsonLd.map((text) => ({ textContent: text }));
      }
      return [];
    },
  };
}

describe("parsePriceText", () => {
  it("parses dollar strings and ignores non-positive values", () => {
    assert.equal(parsePriceText("$2.29"), 2.29);
    assert.equal(parsePriceText("  $14.99 / ea "), 14.99);
    assert.equal(parsePriceText("Sale: $3.49"), 3.49);
    assert.equal(parsePriceText("free"), null);
    assert.equal(parsePriceText(""), null);
  });
});

describe("extractAmazonProduct", () => {
  it("extracts title, offscreen price, size, and Amazon Fresh store from DOM", () => {
    const doc = makeDoc({
      title: "Amazon.com: Schweppes Tonic Water, 1 Liter Bottle : Amazon Fresh",
      selectors: {
        "#productTitle": "  Schweppes Tonic Water, 1 Liter Bottle (Pack of 6) ",
        "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen": "$2.29",
        "#inline-twister-expanded-dimension-text-size_name": "1 Liter (Pack of 6)",
      },
    });
    const result = extractAmazonProduct(
      doc,
      "https://www.amazon.com/Schweppes-Tonic-Water/dp/B001234567?almBrandId=QW1hem9uIEZyZXNo"
    );
    assert.ok(result);
    assert.equal(
      result.title,
      "Schweppes Tonic Water, 1 Liter Bottle (Pack of 6)"
    );
    assert.equal(result.price, 2.29);
    assert.equal(result.size, "1 Liter (Pack of 6)");
    assert.equal(result.store, "Amazon Fresh");
  });

  it("detects Whole Foods Market storefront on Amazon", () => {
    const doc = makeDoc({
      title: "365 by Whole Foods Market, Organic Baby Spinach, 16 Ounce : Whole Foods Market",
      selectors: {
        "#productTitle":
          "365 by Whole Foods Market, Organic Baby Spinach, 16 Ounce",
        "#corePrice_feature_div .a-price .a-offscreen": "$4.99",
      },
    });
    const result = extractAmazonProduct(
      doc,
      "https://www.amazon.com/dp/B074H65L3K"
    );
    assert.ok(result);
    assert.equal(result.store, "Whole Foods Market");
    assert.equal(result.price, 4.99);
  });

  it("returns null on Amazon search or home pages with no product title", () => {
    const doc = makeDoc({ title: "Amazon.com : tonic water" });
    const result = extractAmazonProduct(
      doc,
      "https://www.amazon.com/s?k=tonic+water"
    );
    assert.equal(result, null);
  });
});

describe("extractSafewayProduct", () => {
  it("extracts Product JSON-LD first with GTIN and offer price", () => {
    const doc = makeDoc({
      title: "Signature SELECT Grade AA Large Eggs - 18 Count - Safeway",
      jsonLd: [
        JSON.stringify({
          "@context": "https://schema.org",
          "@type": "Product",
          name: "Signature SELECT Grade AA Large Eggs - 18 Count",
          gtin13: "0002113001234",
          offers: {
            "@type": "Offer",
            price: "4.49",
          },
        }),
      ],
      selectors: {
        '[data-qa="pdp-unit-qty"]': "18 Count",
      },
    });
    const result = extractSafewayProduct(
      doc,
      "https://www.safeway.com/shop/product-details.960012345.html"
    );
    assert.ok(result);
    assert.equal(
      result.title,
      "Signature SELECT Grade AA Large Eggs - 18 Count"
    );
    assert.equal(result.price, 4.49);
    assert.equal(result.gtin, "0002113001234");
    assert.equal(result.size, "18 Count");
    assert.equal(result.store, "Safeway");
  });

  it("falls back to Safeway DOM selectors when JSON-LD is absent", () => {
    const doc = makeDoc({
      title: "Lucerne Milk Whole 1 Gallon - Safeway",
      selectors: {
        '[data-qa="pdp-product-name"]': "Lucerne Milk Whole 1 Gallon - 128 Fl. Oz.",
        '[data-qa="pdp-price"]': "$4.29",
      },
    });
    const result = extractSafewayProduct(
      doc,
      "https://www.safeway.com/shop/product-details.136010011.html"
    );
    assert.ok(result);
    assert.equal(result.title, "Lucerne Milk Whole 1 Gallon - 128 Fl. Oz.");
    assert.equal(result.price, 4.29);
    assert.equal(result.store, "Safeway");
  });

  it("returns null on Safeway browse/search pages", () => {
    const doc = makeDoc({ title: "Search Results | Safeway" });
    const result = extractSafewayProduct(
      doc,
      "https://www.safeway.com/shop/search-results.html?q=milk"
    );
    assert.equal(result, null);
  });
});

describe("extractProductFromPage dispatcher", () => {
  it("routes amazon.com and safeway.com URLs to their adapters", () => {
    const amzDoc = makeDoc({
      title: "Amazon Fresh",
      selectors: {
        "#productTitle": "Kerrygold Pure Irish Butter, 8 oz",
        "#corePrice_feature_div .a-price .a-offscreen": "$4.79",
      },
    });
    const amz = extractProductFromPage(
      amzDoc,
      "https://www.amazon.com/dp/B0001234"
    );
    assert.equal(amz.store, "Amazon Fresh");
    assert.equal(amz.price, 4.79);
  });
});
