(() => {
"use strict";
/**
 * Shared pure helpers for the TruePriceMemory browser extension (Chrome + Firefox).
 */
const DEFAULT_SERVER_URL = "http://127.0.0.1:8000";

const ALLOWED_LOCAL_HOSTS = new Set(["127.0.0.1", "localhost"]);

/**
 * Normalize and validate the Grocery Tracker server base URL.
 * Defaults to http://127.0.0.1:8000 and strips trailing slashes.
 */
function normalizeServerUrl(rawUrl) {
  const trimmed = String(rawUrl ?? "").trim();
  if (!trimmed) {
    return DEFAULT_SERVER_URL;
  }
  let parsed;
  try {
    parsed = new URL(trimmed);
  } catch {
    throw new Error("Server URL must be a valid http:// or https:// URL.");
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("Server URL must use http:// or https://.");
  }
  // Plain HTTP is only safe for loopback; remote tailnet hosts must use HTTPS or .ts.net.
  const host = parsed.hostname.toLowerCase();
  const isLoopback = ALLOWED_LOCAL_HOSTS.has(host);
  const isTailnet = host.endsWith(".ts.net");
  if (parsed.protocol === "http:" && !isLoopback && !isTailnet) {
    throw new Error(
      "Plain http:// is only allowed for 127.0.0.1, localhost, or *.ts.net."
    );
  }
  return `${parsed.protocol}//${parsed.host}`;
}

/**
 * Build a full /api/ext/lookup URL with encoded query parameters.
 */
function buildLookupUrl(
  serverUrl,
  { q = "", store = null, size = null, price = null, gtin = null, limit = 3 } = {}
) {
  const base = normalizeServerUrl(serverUrl);
  const url = new URL("/api/ext/lookup", base);
  if (q && String(q).trim()) {
    url.searchParams.set("q", String(q).trim());
  }
  if (store && String(store).trim()) {
    url.searchParams.set("store", String(store).trim());
  }
  if (size && String(size).trim()) {
    url.searchParams.set("size", String(size).trim());
  }
  if (price !== null && price !== undefined && price !== "") {
    const num = Number(price);
    if (Number.isFinite(num) && num > 0) {
      url.searchParams.set("price", String(num));
    }
  }
  if (gtin && String(gtin).trim()) {
    url.searchParams.set("gtin", String(gtin).trim());
  }
  if (limit && Number.isInteger(Number(limit))) {
    url.searchParams.set("limit", String(limit));
  }
  return url.toString();
}

/**
 * Format a numeric dollar value cleanly.
 */
function formatMoney(amount, symbol = "$") {
  const num = Number(amount);
  if (!Number.isFinite(num)) {
    return "—";
  }
  return `${symbol}${num.toFixed(2)}`;
}

/**
 * Format a unit price with its basis label (e.g. "$0.31 per oz" or "$2.49 each").
 */
function formatUnitPrice(unitPrice, basisLabel = "each", symbol = "$") {
  const num = Number(unitPrice);
  if (!Number.isFinite(num)) {
    return "—";
  }
  const decimals = num < 1 && num > 0 ? 3 : 2;
  const label = basisLabel || "each";
  return `${symbol}${num.toFixed(decimals)} ${label}`;
}

/**
 * Turn a comparison payload from /api/ext/lookup into a human-friendly badge descriptor.
 */
function describeVerdict(comparison) {
  if (!comparison) {
    return null;
  }
  if (!comparison.unit_compatible) {
    return {
      verdict: "incompatible",
      tone: "neutral",
      label: "Different unit basis",
      detail: `History is tracked ${comparison.basis_label || "on a different basis"}`,
    };
  }
  const pct = Number(comparison.delta_pct);
  const pctText = Number.isFinite(pct)
    ? `${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`
    : "";

  if (comparison.verdict === "good_deal") {
    return {
      verdict: "good_deal",
      tone: "good",
      label: `Good deal (${pctText})`,
      detail: `${formatUnitPrice(comparison.page_unit_price, comparison.basis_label)} vs avg ${formatUnitPrice(comparison.comparable_past_price, comparison.basis_label)}`,
    };
  }
  if (comparison.verdict === "pricier") {
    return {
      verdict: "pricier",
      tone: "warn",
      label: `Above avg (${pctText})`,
      detail: `${formatUnitPrice(comparison.page_unit_price, comparison.basis_label)} vs avg ${formatUnitPrice(comparison.comparable_past_price, comparison.basis_label)}`,
    };
  }
  if (comparison.verdict === "typical") {
    return {
      verdict: "typical",
      tone: "info",
      label: `Typical price (${pctText || "≈ avg"})`,
      detail: `${formatUnitPrice(comparison.page_unit_price, comparison.basis_label)} vs avg ${formatUnitPrice(comparison.comparable_past_price, comparison.basis_label)}`,
    };
  }
  return null;
}

/**
 * Infer a canonical store name from a browser tab URL and optional page title.
 */
function inferStoreFromUrl(urlString, pageTitle = "") {
  if (!urlString) {
    return null;
  }
  let host = "";
  let path = "";
  try {
    const u = new URL(urlString);
    host = u.hostname.toLowerCase();
    path = (u.pathname + u.search).toLowerCase();
  } catch {
    return null;
  }
  const titleLower = String(pageTitle || "").toLowerCase();

  if (host.includes("safeway.com")) {
    return "Safeway";
  }
  if (host.includes("wholefoodsmarket.com")) {
    return "Whole Foods Market";
  }
  if (host.includes("amazon.com")) {
    if (
      path.includes("alm") ||
      path.includes("wholefoods") ||
      titleLower.includes("whole foods")
    ) {
      if (titleLower.includes("whole foods") || path.includes("wholefoods")) {
        return "Whole Foods Market";
      }
      return "Amazon Fresh";
    }
    if (path.includes("fresh") || titleLower.includes("amazon fresh")) {
      return "Amazon Fresh";
    }
    return "Amazon Fresh";
  }
  return null;
}

/**
 * Extract structured Product metadata ({ title, price, gtin, size }) from an
 * array of raw JSON-LD script contents on a product page.
 */
function parseJsonLdProduct(jsonStrings) {
  if (!Array.isArray(jsonStrings)) {
    return null;
  }

  const visit = (node) => {
    if (!node || typeof node !== "object") {
      return null;
    }
    if (Array.isArray(node)) {
      for (const item of node) {
        const found = visit(item);
        if (found) return found;
      }
      return null;
    }
    const rawType = node["@type"];
    const types = Array.isArray(rawType) ? rawType : [rawType];
    const isProduct = types.some(
      (t) => typeof t === "string" && t.toLowerCase().includes("product")
    );
    if (isProduct && node.name) {
      let price = null;
      const offers = Array.isArray(node.offers) ? node.offers[0] : node.offers;
      if (offers && typeof offers === "object") {
        const rawPrice = offers.price ?? offers.lowPrice ?? offers?.priceSpecification?.price;
        const parsedPrice = Number(String(rawPrice ?? "").replace(/[^0-9.]/g, ""));
        if (Number.isFinite(parsedPrice) && parsedPrice > 0) {
          price = parsedPrice;
        }
      }
      const gtin =
        node.gtin13 || node.gtin12 || node.gtin14 || node.gtin || node.sku || null;
      return {
        title: String(node.name).trim(),
        price,
        gtin: gtin ? String(gtin).trim() : null,
      };
    }
    if (Array.isArray(node["@graph"])) {
      return visit(node["@graph"]);
    }
    return null;
  };

  for (const raw of jsonStrings) {
    if (!raw || typeof raw !== "string") continue;
    try {
      const parsed = JSON.parse(raw);
      const hit = visit(parsed);
      if (hit) return hit;
    } catch {
      // Ignore malformed JSON-LD blocks on retail pages
    }
  }
  return null;
}

const BRAND_PREFIX_RE =
  /^\s*(?:365\s+by\s+whole\s+foods\s+market|whole\s+foods\s+market|amazon\s+brand\s*[-–—]?\s*happy\s+belly|amazon\s+brand\s*[-–—]?\s*solimo|amazon\s+fresh|happy\s+belly|signature\s+select|signature\s+farms|signature\s+care|o\s+organics|open\s+nature)\b[\s,:-]*/i;

const PAREN_PACK_RE =
  /\((?:[^)]*\b(?:pack|pk|count|ct|oz|ounce|lb|pound|liter|litre|ml|gal|g|kg)\b[^)]*)\)/gi;

const SIZE_TOKEN_RE =
  /\b(?:pack\s+of\s+\d+|\d+\s*[-–]?\s*(?:pack|pk|count|ct|cnt)\b|\d+(?:\.\d+)?\s*(?:x\s*\d+(?:\.\d+)?)?\s*(?:fl\.?\s*oz\.?|fluid\s+ounces?|ounces?|oz\.?|pounds?|lbs?\.?|grams?|g|kilograms?|kg|milliliters?|ml|liters?|litres?|l|gallons?|gal|quarts?|qt|pints?|pt)\b)/gi;

const CONTAINER_WORDS = new Set([
  "bottle",
  "bottles",
  "can",
  "cans",
  "jar",
  "jars",
  "box",
  "boxes",
  "bag",
  "bags",
  "carton",
  "cartons",
  "tub",
  "tubs",
  "cup",
  "cups",
  "pouch",
  "pouches",
  "container",
  "containers",
  "package",
  "packages",
  "pack",
  "packs",
]);

const QUALIFIER_WORDS = new Set([
  "organic",
  "fresh",
  "natural",
  "raw",
  "pure",
  "whole",
  "large",
  "medium",
  "small",
  "extra",
  "grade",
  "select",
  "choice",
  "prime",
  "original",
  "classic",
  "traditional",
  "homestyle",
  "artisan",
  "premium",
  "fancy",
  "kosher",
  "gluten",
  "free",
  "non",
  "gmo",
  "unsalted",
  "salted",
  "sweetened",
  "unsweetened",
  "light",
  "lite",
  "low",
  "fat",
  "reduced",
  "diet",
  "zero",
]);

const TO_OZ = {
  oz: 1.0,
  "fl oz": 1.0,
  lb: 16.0,
  g: 1.0 / 28.3495,
  kg: 35.27396,
  ml: 1.0 / 29.5735,
  l: 33.814,
  pt: 16.0,
  qt: 32.0,
  gal: 128.0,
};

const COUNT_UNITS = new Set(["ct", "count", "ea", "each", "pk", "pack", "pc", "pcs"]);
function cleanRetailTitle(title) {
  if (!title) return "";
  let text = String(title).trim().replace(BRAND_PREFIX_RE, " ");
  text = text.replace(PAREN_PACK_RE, " ");
  text = text.replace(SIZE_TOKEN_RE, " ");
  text = text.toLowerCase().replace(/[^a-z0-9]+/g, " ");
  const tokens = text
    .split(/\s+/)
    .filter((tok) => tok && !CONTAINER_WORDS.has(tok));
  if (tokens.length > 0) {
    return tokens.join(" ");
  }
  return String(title)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function canonUnit(rawUnit) {
  const u = String(rawUnit || "")
    .toLowerCase()
    .replace(/\./g, "")
    .replace(/\s+/g, " ")
    .trim();
  if (["fl oz", "floz", "fluid ounce", "fluid ounces"].includes(u)) return "fl oz";
  if (["oz", "ounce", "ounces"].includes(u)) return "oz";
  if (["lb", "lbs", "pound", "pounds"].includes(u)) return "lb";
  if (["g", "gram", "grams"].includes(u)) return "g";
  if (["kg", "kilogram", "kilograms"].includes(u)) return "kg";
  if (["ml", "milliliter", "milliliters"].includes(u)) return "ml";
  if (["l", "liter", "liters", "litre", "litres"].includes(u)) return "l";
  if (["gal", "gallon", "gallons"].includes(u)) return "gal";
  if (["qt", "quart", "quarts"].includes(u)) return "qt";
  if (["pt", "pint", "pints"].includes(u)) return "pt";
  return u;
}
function parseRetailSize(text) {
  if (!text) return null;
  const str = String(text);
  let packCount = 1;
  const packMatch = str.match(
    /(?:pack\s+of\s+(\d+)|(\d+)\s*[-–]?\s*(?:pack|pk)\b|(\d+)\s*(?:ct|count)\b\s*,?)/i
  );
  if (packMatch) {
    const found = packMatch[1] || packMatch[2] || packMatch[3];
    if (found) packCount = Math.max(1, parseInt(found, 10));
  } else {
    const multMatch = str.match(/\b(\d+)\s*x\s*\d+(?:\.\d+)?/i);
    if (multMatch) packCount = Math.max(1, parseInt(multMatch[1], 10));
  }

  const measureMatch = str.match(
    /(\d+(?:\.\d+)?)\s*(fl\.?\s*oz\.?|fluid\s+ounces?|ounces?|oz\.?|pounds?|lbs?\.?|grams?|g|kilograms?|kg|milliliters?|ml|liters?|litres?|l|gallons?|gal|quarts?|qt|pints?|pt)\b/i
  );
  if (measureMatch) {
    const amount = parseFloat(measureMatch[1]);
    const unit = canonUnit(measureMatch[2]);
    const factor = TO_OZ[unit];
    const totalOz = factor ? Number((amount * factor * packCount).toFixed(4)) : null;
    return {
      amount,
      unit,
      pack_count: packCount,
      total_oz: totalOz,
      total_count: packCount > 1 ? packCount : null,
    };
  }

  const countMatch = str.match(
    /(?:(\d+(?:\.\d+)?)\s*(?:count|ct|cnt|pk|pack)\b|pack\s+of\s+(\d+))/i
  );
  if (countMatch) {
    const cnt = parseFloat(countMatch[1] || countMatch[2]);
    if (cnt > 0) {
      return {
        amount: cnt,
        unit: "ct",
        pack_count: Math.round(cnt),
        total_oz: null,
        total_count: cnt,
      };
    }
  }
  return null;
}

function normalizeGtin(gtin) {
  if (!gtin) return "";
  return String(gtin).replace(/\D+/g, "").replace(/^0+/, "");
}

function scoreOfflineMatch(cleanedQuery, cleanedItem) {
  if (!cleanedQuery || !cleanedItem) return 0;
  if (cleanedQuery === cleanedItem) return 100;

  const qTokens = new Set(cleanedQuery.split(/\s+/).filter((t) => t.length > 1));
  const iTokens = new Set(cleanedItem.split(/\s+/).filter((t) => t.length > 1));
  if (qTokens.size === 0 || iTokens.size === 0) return 0;

  const shared = [...qTokens].filter((t) => iTokens.has(t));
  const substantive = shared.filter((t) => !QUALIFIER_WORDS.has(t));
  if (substantive.length === 0) {
    return 0;
  }

  const iSubsetOfQ = [...iTokens].every((t) => qTokens.has(t));
  const qSubsetOfI = [...qTokens].every((t) => iTokens.has(t));
  const smaller = Math.min(qTokens.size, iTokens.size);
  const larger = Math.max(qTokens.size, iTokens.size);

  if (shared.length >= 2 && (iSubsetOfQ || qSubsetOfI)) {
    const coverage = smaller / larger;
    return Math.min(99, Math.round(88 + 10 * coverage));
  }

  if (shared.length === 1 && (iSubsetOfQ || qSubsetOfI)) {
    return larger === 2 ? 78 : 55;
  }

  const unionSize = new Set([...qTokens, ...iTokens]).size;
  const jaccard = shared.length / unionSize;
  const dice = (2 * shared.length) / (qTokens.size + iTokens.size);
  return Math.min(98, Math.round(dice * 75 + jaccard * 25));
}

function compareOfflineOffer({ basis, basisLabel, comparableAvg, pagePrice, parsedSize }) {
  const numPrice = Number(pagePrice);
  if (!Number.isFinite(numPrice) || numPrice <= 0) return null;

  let pageUnitPrice = null;
  let compatible = false;

  if (TO_OZ[basis]) {
    if (parsedSize?.total_oz && parsedSize.total_oz > 0) {
      const amountInBasis = parsedSize.total_oz / TO_OZ[basis];
      if (amountInBasis > 0) {
        pageUnitPrice = Number((numPrice / amountInBasis).toFixed(4));
        compatible = true;
      }
    }
  } else if (COUNT_UNITS.has(basis)) {
    if (parsedSize?.total_count && parsedSize.total_count > 0) {
      pageUnitPrice = Number((numPrice / parsedSize.total_count).toFixed(4));
      compatible = true;
    }
  } else if (!basis || basis === "each") {
    if (!parsedSize || parsedSize.pack_count === 1) {
      pageUnitPrice = Number(numPrice.toFixed(4));
      compatible = true;
    } else if (parsedSize.total_count && parsedSize.total_oz === null) {
      pageUnitPrice = Number((numPrice / parsedSize.total_count).toFixed(4));
      compatible = true;
    }
  }

  let deltaPct = null;
  let verdict = null;
  if (
    compatible &&
    pageUnitPrice !== null &&
    Number.isFinite(Number(comparableAvg)) &&
    Number(comparableAvg) > 0
  ) {
    deltaPct = Number(
      (((pageUnitPrice - Number(comparableAvg)) / Number(comparableAvg)) * 100).toFixed(1)
    );
    if (deltaPct <= -5.0) verdict = "good_deal";
    else if (deltaPct >= 5.0) verdict = "pricier";
    else verdict = "typical";
  }

  return {
    page_price: Number(numPrice.toFixed(2)),
    page_unit_price: pageUnitPrice,
    comparable_past_price:
      comparableAvg !== null && comparableAvg !== undefined
        ? Number(Number(comparableAvg).toFixed(4))
        : null,
    basis: basis || "each",
    basis_label: basisLabel || "each",
    unit_compatible: compatible,
    delta_pct: deltaPct,
    verdict,
  };
}

/**
 * Match a product query against a cached /api/ext/snapshot item list when the
 * local Grocery Tracker server is offline or unreachable.
 */
function matchOfflineSnapshot(
  snapshotItems,
  { q = "", store = null, size = null, price = null, gtin = null, limit = 3 } = {}
) {
  const items = Array.isArray(snapshotItems) ? snapshotItems : [];
  const cleanedQ = cleanRetailTitle(q);
  const normGtin = normalizeGtin(gtin);
  const canonicalStore = store && String(store).trim() ? String(store).trim() : null;
  const parsedSize = parseRetailSize(size) || parseRetailSize(q);

  const candidates = [];
  for (const item of items) {
    if (normGtin && normalizeGtin(item.gtin) === normGtin) {
      candidates.push({ item, confidence: 100, matched_by: "gtin" });
      continue;
    }
    if (!cleanedQ) continue;
    const itemClean = item.cleaned_name || cleanRetailTitle(item.name || "");
    const score = scoreOfflineMatch(cleanedQ, itemClean);
    if (score >= 70) {
      candidates.push({ item, confidence: score, matched_by: "name" });
    }
  }

  candidates.sort((a, b) => {
    const aGtin = a.matched_by === "gtin" ? 1 : 0;
    const bGtin = b.matched_by === "gtin" ? 1 : 0;
    if (aGtin !== bGtin) return bGtin - aGtin;

    const aHasStore =
      canonicalStore &&
      Array.isArray(a.item.stores) &&
      a.item.stores.some((s) => s.store === canonicalStore);
    const bHasStore =
      canonicalStore &&
      Array.isArray(b.item.stores) &&
      b.item.stores.some((s) => s.store === canonicalStore);

    const aRank = a.confidence + (aHasStore ? 4 : 0);
    const bRank = b.confidence + (bHasStore ? 4 : 0);
    if (bRank !== aRank) return bRank - aRank;
    return b.confidence - a.confidence;
  });

  const cappedLimit = Math.max(1, Math.min(Number(limit) || 3, 10));
  const matches = candidates.slice(0, cappedLimit).map(({ item, confidence, matched_by }) => {
    const atThisStore =
      canonicalStore && Array.isArray(item.stores)
        ? item.stores.find((s) => s.store === canonicalStore) || null
        : null;
    const comparison = compareOfflineOffer({
      basis: item.basis || "each",
      basisLabel: item.basis_label || "each",
      comparableAvg: item.comparable_avg ?? item.last_paid?.unit_price ?? null,
      pagePrice: price,
      parsedSize,
    });
    return {
      item_id: item.item_id,
      name: item.name,
      confidence,
      matched_by,
      unit: item.unit ?? null,
      basis: item.basis || "each",
      basis_label: item.basis_label || "each",
      last_paid: item.last_paid,
      at_this_store: atThisStore,
      all_stores: item.all_stores,
      history: [],
      comparison,
    };
  });

  return {
    query: q,
    cleaned_query: cleanedQ,
    store: canonicalStore,
    matches,
  };
}


/**
 * Retailer DOM and JSON-LD product extractors for Amazon Fresh / Whole Foods and Safeway.
 *
 * Pure functions operating on a document-like object and URL string so they can
 * be unit-tested in Node against HTML fixtures and run passively inside the
 * browser tab without triggering network requests or mutating retailer DOM.
 */

/**
 * Extract the first positive dollar figure from a text string (e.g. "$2.29" -> 2.29).
 */
function parsePriceText(raw) {
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
function extractAmazonProduct(doc, urlString) {
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
function extractSafewayProduct(doc, urlString) {
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
function extractProductFromPage(doc, urlString) {
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


/**
 * Passive content script for Amazon Fresh and Safeway product pages.
 *
 * Extracts the viewed product, asks the background service worker to query the
 * local Grocery Tracker server, and renders an unobtrusive floating badge inside
 * a closed Shadow DOM attached to document.documentElement so the retailer's own
 * DOM tree and hydration state are never touched.
 */


const ext = globalThis.browser ?? globalThis.chrome;
const HOST_ID = "tpm-price-memory-root";

let shadowRoot = null;
let lastSignature = "";
let debounceTimer = null;

const BADGE_STYLES = `
  :host {
    all: initial;
  }
  .tpm-badge {
    position: fixed;
    right: 18px;
    bottom: 18px;
    z-index: 2147483646;
    width: 310px;
    max-width: calc(100vw - 36px);
    background: #0f172a;
    color: #f8fafc;
    border: 1px solid #334155;
    border-radius: 14px;
    box-shadow: 0 14px 32px rgba(0, 0, 0, 0.45);
    font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 12px;
    line-height: 1.4;
    padding: 11px 13px;
  }
  .tpm-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }
  .tpm-brand {
    font-weight: 700;
    font-size: 11px;
    letter-spacing: 0.03em;
    color: #94a3b8;
    text-transform: uppercase;
  }
  .tpm-close {
    background: transparent;
    border: none;
    color: #94a3b8;
    cursor: pointer;
    font-size: 15px;
    line-height: 1;
    padding: 2px 5px;
    border-radius: 6px;
  }
  .tpm-close:hover {
    color: #f8fafc;
    background: #1e293b;
  }
  .tpm-item-name {
    margin-top: 4px;
    font-weight: 700;
    font-size: 13px;
    color: #f8fafc;
  }
  .tpm-pill {
    display: inline-block;
    margin-top: 6px;
    padding: 3px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 600;
  }
  .tpm-pill.good {
    background: rgba(16, 185, 129, 0.18);
    color: #6ee7b7;
  }
  .tpm-pill.warn {
    background: rgba(245, 158, 11, 0.18);
    color: #fcd34d;
  }
  .tpm-pill.info, .tpm-pill.neutral {
    background: rgba(99, 102, 241, 0.18);
    color: #a5b4fc;
  }
  .tpm-rows {
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px solid #1e293b;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .tpm-row {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    color: #cbd5e1;
  }
  .tpm-row strong {
    color: #f8fafc;
  }
  .tpm-muted {
    margin-top: 4px;
    color: #94a3b8;
    font-size: 11px;
  }
`;

function ensureShadowRoot() {
  let host = document.getElementById(HOST_ID);
  if (!host) {
    host = document.createElement("div");
    host.id = HOST_ID;
    shadowRoot = host.attachShadow({ mode: "closed" });
    (document.body || document.documentElement).appendChild(host);
  }
  return shadowRoot;
}

function clearBadge() {
  const host = document.getElementById(HOST_ID);
  if (host) {
    host.remove();
  }
  shadowRoot = null;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function renderBadge(result, product) {
  if (!result || !result.ok) {
    clearBadge();
    return;
  }
  const matches = result.data?.matches || [];
  const root = ensureShadowRoot();
  if (!root) return;
  root.replaceChildren();

  const style = document.createElement("style");
  style.textContent = BADGE_STYLES;
  root.appendChild(style);

  const box = el("aside", "tpm-badge");
  box.setAttribute("role", "status");
  box.setAttribute("aria-label", "TruePriceMemory price history");

  const top = el("div", "tpm-top");
  const brandLabel = result.offline
    ? "🧾 TruePriceMemory · Offline"
    : "🧾 TruePriceMemory";
  top.appendChild(el("span", "tpm-brand", brandLabel));
  const closeBtn = el("button", "tpm-close", "×");
  closeBtn.setAttribute("aria-label", "Dismiss price badge");
  closeBtn.addEventListener("click", clearBadge);
  top.appendChild(closeBtn);
  box.appendChild(top);

  if (matches.length === 0) {
    box.appendChild(
      el("div", "tpm-muted", `No purchase history for "${product.title.slice(0, 48)}".`)
    );
    root.appendChild(box);
    return;
  }

  const topMatch = matches[0];
  box.appendChild(el("div", "tpm-item-name", topMatch.name));

  const verdict = describeVerdict(topMatch.comparison);
  if (verdict) {
    box.appendChild(el("span", `tpm-pill ${verdict.tone}`, verdict.label));
  }

  const rows = el("div", "tpm-rows");

  const lastRow = el("div", "tpm-row");
  lastRow.appendChild(
    el("span", "", `Last (${topMatch.last_paid.store}, ${topMatch.last_paid.date || "—"})`)
  );
  const unitNote =
    topMatch.last_paid.basis !== "each"
      ? ` (${formatUnitPrice(topMatch.last_paid.unit_price, topMatch.last_paid.basis_label)})`
      : "";
  lastRow.appendChild(
    el("strong", "", `${formatMoney(topMatch.last_paid.price)}${unitNote}`)
  );
  rows.appendChild(lastRow);

  const bestRow = el("div", "tpm-row");
  bestRow.appendChild(
    el(
      "span",
      "",
      `Best (${topMatch.all_stores.best_store} · ${topMatch.all_stores.total_purchases}×)`
    )
  );
  bestRow.appendChild(el("strong", "", formatMoney(topMatch.all_stores.best_price)));
  rows.appendChild(bestRow);

  box.appendChild(rows);
  root.appendChild(box);
}

async function inspectCurrentPage() {
  if (typeof document === "undefined" || !ext?.runtime?.sendMessage) return;
  const product = extractProductFromPage(document, window.location.href);
  if (!product) {
    lastSignature = "";
    clearBadge();
    return;
  }

  const signature = `${product.store}|${product.title}|${product.price ?? ""}|${product.size ?? ""}`;
  if (signature === lastSignature) {
    return;
  }
  lastSignature = signature;

  try {
    const resp = await ext.runtime.sendMessage({
      type: "tpm:page-product",
      payload: {
        q: product.title,
        store: product.store,
        price: product.price,
        size: product.size,
        gtin: product.gtin,
      },
    });
    renderBadge(resp, product);
  } catch {
    // Extension context invalidated or background worker reloading
  }
}

function scheduleInspect() {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(inspectCurrentPage, 600);
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  inspectCurrentPage();
  const titleEl = document.querySelector("title");
  if (titleEl && typeof MutationObserver !== "undefined") {
    const observer = new MutationObserver(scheduleInspect);
    observer.observe(titleEl, { childList: true, subtree: true, characterData: true });
  }
  window.addEventListener("popstate", scheduleInspect, { passive: true });
}

})();
