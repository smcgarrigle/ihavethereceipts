/**
 * Passive content script for Amazon Fresh and Safeway product pages.
 *
 * Extracts the viewed product, asks the background service worker to query the
 * local Grocery Tracker server, and renders an unobtrusive floating badge inside
 * a closed Shadow DOM attached to document.documentElement so the retailer's own
 * DOM tree and hydration state are never touched.
 */

import { describeVerdict, formatMoney, formatUnitPrice } from "../common.js";
import { extractProductFromPage } from "./extractors.js";

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
