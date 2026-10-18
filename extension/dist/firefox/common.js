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
