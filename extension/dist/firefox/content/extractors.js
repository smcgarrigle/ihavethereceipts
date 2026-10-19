/**
 * Retailer DOM and JSON-LD product extractors for Amazon Fresh / Whole Foods and Safeway.
 *
 * Pure functions operating on a document-like object and URL string so they can
 * be unit-tested in Node against HTML fixtures and run passively inside the
 * browser tab without triggering network requests or mutating retailer DOM.
 */

import { inferStoreFromUrl, parseJsonLdProduct } from "../common.js";

/**
 * Extract the first positive dollar figure from a text string (e.g. "$2.29" -> 2.29).
 */
export function parsePriceText(raw) {
  if (!raw) return null;
  const text = String(raw).trim();
  const match = text.match(/\$?\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)/);
  if (!match) return null;
  const value = Number(match[1].replace(/,/g, ""));
  return Number.isFinite(value) && value > 0 ? value : null;
}

function readText(doc, selectors) {
  for (const sel of selectors) {
    const el = doc.querySelector(sel);
    if (el && el.textContent && el.textContent.trim()) {
      return el.textContent.trim().replace(/\s+/g, " ");
    }
  }
  return null;
}

function readJsonLdScripts(doc) {
  const nodes = doc.querySelectorAll('script[type="application/ld+json"]') || [];
  const list = [];
  for (const node of nodes) {
    if (node && node.textContent) {
      list.push(node.textContent);
    }
  }
  return list;
}

/**
 * Extract product details from an Amazon Fresh / Whole Foods / Amazon product page.
 */
export function extractAmazonProduct(doc, urlString) {
  if (!doc) return null;
  const ld = parseJsonLdProduct(readJsonLdScripts(doc));

  const title =
    ld?.title ||
    readText(doc, [
      "#productTitle",
      "#title",
      "h1#title span",
      '[data-feature-name="title"] h1',
    ]);

  if (!title) {
    return null;
  }

  let price = ld?.price ?? null;
  if (!price) {
    const priceText = readText(doc, [
      "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
      "#corePrice_feature_div .a-price .a-offscreen",
      "#apex_desktop .a-price .a-offscreen",
      ".reinventPricePriceToPayMargin .a-offscreen",
      "#priceblock_ourprice",
      "#priceblock_dealprice",
      "#tp_price_block_total_price_ww .a-offscreen",
    ]);
    price = parsePriceText(priceText);
  }

  const size = readText(doc, [
    "#inline-twister-expanded-dimension-text-size_name",
    "#variation_size_name .selection",
    "#twister .Swatches-selected",
  ]);

  const byline = readText(doc, ["#almLogo", "#almByline", "#bylineInfo"]) || "";
  const store =
    inferStoreFromUrl(urlString, `${doc.title || ""} ${byline} ${title}`) ||
    "Amazon Fresh";

  return {
    title,
    price,
    size: size || null,
    gtin: ld?.gtin || null,
    store,
    url: urlString || "",
  };
}

/**
 * Extract product details from a Safeway (safeway.com) product detail page.
 *
 * Uses passive JSON-LD and DOM reads only — never calls Safeway APIs or modifies
 * Safeway's React/Angular component tree.
 */
export function extractSafewayProduct(doc, urlString) {
  if (!doc) return null;
  const ld = parseJsonLdProduct(readJsonLdScripts(doc));

  const title =
    ld?.title ||
    readText(doc, [
      '[data-qa="pdp-product-name"]',
      "h1.product-title",
      ".pdp-product-name h1",
      "main h1",
    ]);

  if (!title) {
    return null;
  }

  let price = ld?.price ?? null;
  if (!price) {
    const priceText = readText(doc, [
      '[data-qa="pdp-price"]',
      ".price-xl",
      ".product-price__saleprice",
      ".product-price",
      '[class*="price-header"]',
    ]);
    price = parsePriceText(priceText);
  }

  const size = readText(doc, [
    '[data-qa="pdp-unit-qty"]',
    ".product-Spoon-size",
    ".pdp-unit-qty",
  ]);

  return {
    title,
    price,
    size: size || null,
    gtin: ld?.gtin || null,
    store: "Safeway",
    url: urlString || "",
  };
}

/**
 * Route the current document and URL to the matching retailer adapter.
 */
export function extractProductFromPage(doc, urlString) {
  if (!doc || !urlString) return null;
  let host = "";
  try {
    host = new URL(urlString).hostname.toLowerCase();
  } catch {
    return null;
  }
  if (host.includes("safeway.com")) {
    return extractSafewayProduct(doc, urlString);
  }
  if (host.includes("amazon.com")) {
    return extractAmazonProduct(doc, urlString);
  }
  return null;
}
