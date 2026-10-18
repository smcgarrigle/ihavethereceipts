import {
  describeVerdict,
  formatMoney,
  formatUnitPrice,
  inferStoreFromUrl,
} from "../common.js";

const ext = globalThis.browser ?? globalThis.chrome;

const setupPrompt = document.getElementById("setup-prompt");
const setupBtn = document.getElementById("setup-btn");
const openOptionsBtn = document.getElementById("open-options-btn");
const form = document.getElementById("lookup-form");
const queryInput = document.getElementById("query-input");
const storeSelect = document.getElementById("store-select");
const priceInput = document.getElementById("price-input");
const resultsArea = document.getElementById("results-area");

function openOptions() {
  if (ext.runtime?.openOptionsPage) {
    ext.runtime.openOptionsPage();
  }
}

openOptionsBtn.addEventListener("click", openOptions);
setupBtn.addEventListener("click", openOptions);

function createEl(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined && text !== null) el.textContent = String(text);
  return el;
}

function renderMatchCard(match) {
  const card = createEl("article", "match-card");

  const header = createEl("div", "match-header");
  header.appendChild(createEl("div", "match-name", match.name));
  const badgeText =
    match.matched_by === "gtin" ? "Barcode match" : `${match.confidence}% match`;
  header.appendChild(createEl("span", "confidence-badge", badgeText));
  card.appendChild(header);

  const verdict = describeVerdict(match.comparison);
  if (verdict) {
    const pill = createEl("div", `verdict-pill ${verdict.tone}`);
    pill.appendChild(createEl("span", "", verdict.label));
    if (verdict.detail) {
      pill.appendChild(createEl("span", "verdict-detail", verdict.detail));
    }
    card.appendChild(pill);
  }

  const grid = createEl("div", "stats-grid");

  // Box 1: Last Paid
  const lastBox = createEl("div", "stat-box");
  lastBox.appendChild(createEl("div", "stat-label", "Last Paid"));
  lastBox.appendChild(
    createEl("div", "stat-value", formatMoney(match.last_paid.price))
  );
  const lastUnit =
    match.last_paid.basis !== "each"
      ? ` (${formatUnitPrice(match.last_paid.unit_price, match.last_paid.basis_label)})`
      : "";
  lastBox.appendChild(
    createEl(
      "div",
      "stat-sub",
      `${match.last_paid.store}${lastUnit} · ${match.last_paid.date || "—"}`
    )
  );
  grid.appendChild(lastBox);

  // Box 2: Best Across All Stores (or At This Store if available)
  const bestBox = createEl("div", "stat-box");
  bestBox.appendChild(createEl("div", "stat-label", "Best Price Paid"));
  bestBox.appendChild(
    createEl("div", "stat-value", formatMoney(match.all_stores.best_price))
  );
  bestBox.appendChild(
    createEl(
      "div",
      "stat-sub",
      `${match.all_stores.best_store} · avg ${formatMoney(match.all_stores.avg_price)} (${match.all_stores.total_purchases}×)`
    )
  );
  grid.appendChild(bestBox);

  card.appendChild(grid);

  if (match.at_this_store) {
    const storeLine = createEl(
      "div",
      "stat-sub",
      `At ${match.at_this_store.store}: last ${formatMoney(match.at_this_store.last_price)}, min ${formatMoney(match.at_this_store.min_price)} (${match.at_this_store.count}×)`
    );
    card.appendChild(storeLine);
  }

  if (Array.isArray(match.history) && match.history.length > 0) {
    const details = createEl("details", "history-details");
    details.appendChild(
      createEl("summary", "", `Purchase history (${match.history.length})`)
    );
    const list = createEl("ul", "history-list");
    for (const h of match.history) {
      const li = createEl("li", "history-item");
      li.appendChild(createEl("span", "", `${h.date || "—"} · ${h.store}`));
      li.appendChild(createEl("strong", "", formatMoney(h.price)));
      list.appendChild(li);
    }
    details.appendChild(list);
    card.appendChild(details);
  }

  return card;
}

function renderLookupResult(result) {
  resultsArea.replaceChildren();
  if (!result) {
    resultsArea.appendChild(
      createEl(
        "p",
        "empty-state",
        "Highlight any product title and right-click Look up in TruePriceMemory, or search above."
      )
    );
    return;
  }
  if (!result.ok) {
    resultsArea.appendChild(
      createEl("p", "error-state", result.error || "Lookup failed.")
    );
    return;
  }
  const matches = result.data?.matches || [];
  if (matches.length === 0) {
    resultsArea.appendChild(
      createEl(
        "p",
        "empty-state",
        `No purchase history found for "${result.data?.query || queryInput.value}".`
      )
    );
    return;
  }
  for (const match of matches) {
    resultsArea.appendChild(renderMatchCard(match));
  }
}

async function runLookup(payload) {
  resultsArea.replaceChildren(createEl("p", "empty-state", "Looking up…"));
  const resp = await ext.runtime.sendMessage({
    type: "tpm:lookup",
    payload,
  });
  renderLookupResult(resp);
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = queryInput.value.trim();
  if (!q) return;
  const store = storeSelect.value || null;
  const price = priceInput.value ? Number(priceInput.value) : null;
  await runLookup({ q, store, price });
});

async function initPopup() {
  let activeTab = null;
  if (ext.tabs?.query) {
    const tabs = await ext.tabs.query({ active: true, currentWindow: true });
    activeTab = tabs?.[0] || null;
  }

  const state = await ext.runtime.sendMessage({
    type: "tpm:get-state",
    tabId: activeTab?.id || null,
  });

  if (!state?.hasToken) {
    setupPrompt.classList.remove("hidden");
  }

  const inferredStore = inferStoreFromUrl(activeTab?.url || "", activeTab?.title || "");
  if (inferredStore) {
    storeSelect.value = inferredStore;
  }

  if (state?.tabProduct?.title) {
    queryInput.value = state.tabProduct.title;
    if (state.tabProduct.price) {
      priceInput.value = String(state.tabProduct.price);
    }
    if (state.tabProduct.store) {
      storeSelect.value = state.tabProduct.store;
    }
    if (state.hasToken) {
      await runLookup({
        q: state.tabProduct.title,
        store: state.tabProduct.store || inferredStore,
        price: state.tabProduct.price || null,
        size: state.tabProduct.size || null,
        gtin: state.tabProduct.gtin || null,
      });
      return;
    }
  }

  if (state?.lastLookup) {
    if (state.lastLookup.params?.q) {
      queryInput.value = state.lastLookup.params.q;
    }
    if (state.lastLookup.params?.store) {
      storeSelect.value = state.lastLookup.params.store;
    }
    renderLookupResult(state.lastLookup);
  }
}

initPopup();
