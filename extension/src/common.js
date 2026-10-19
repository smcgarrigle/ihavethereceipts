/**
 * Shared pure helpers for the TruePriceMemory browser extension (Chrome + Firefox).
 */

export const DEFAULT_SERVER_URL = "http://127.0.0.1:8000";

const ALLOWED_LOCAL_HOSTS = new Set(["127.0.0.1", "localhost"]);

/**
 * Normalize and validate the Grocery Tracker server base URL.
 * Defaults to http://127.0.0.1:8000 and strips trailing slashes.
 */
export function normalizeServerUrl(rawUrl) {
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
export function buildLookupUrl(
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
export function formatMoney(amount, symbol = "$") {
  const num = Number(amount);
  if (!Number.isFinite(num)) {
    return "—";
  }
  return `${symbol}${num.toFixed(2)}`;
}

/**
 * Format a unit price with its basis label (e.g. "$0.31 per oz" or "$2.49 each").
 */
export function formatUnitPrice(unitPrice, basisLabel = "each", symbol = "$") {
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
export function describeVerdict(comparison) {
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
export function inferStoreFromUrl(urlString, pageTitle = "") {
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
export function parseJsonLdProduct(jsonStrings) {
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

export function cleanRetailTitle(title) {
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

export function parseRetailSize(text) {
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
export function matchOfflineSnapshot(
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
