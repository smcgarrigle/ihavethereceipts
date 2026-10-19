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
  top.appendChild(el("span", "tpm-brand", "🧾 TruePriceMemory"));
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
