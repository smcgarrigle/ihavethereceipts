/**
 * Background service worker / script for the TruePriceMemory browser extension.
 * All requests to the local Grocery Tracker server go through this worker.
 */

import {
  DEFAULT_SERVER_URL,
  buildLookupUrl,
  inferStoreFromUrl,
  matchOfflineSnapshot,
  normalizeServerUrl,
} from "./common.js";

const ext = globalThis.browser ?? globalThis.chrome;
const CONTEXT_MENU_ID = "tpm-lookup-selection";
const SNAPSHOT_STALE_MS = 30 * 60 * 1000;

const tabProducts = new Map();

async function getConfig() {
  const stored = await ext.storage.local.get(["serverUrl", "token"]);
  return {
    serverUrl: stored.serverUrl || DEFAULT_SERVER_URL,
    token: stored.token || "",
  };
}

async function syncSnapshot({ serverUrl, token } = {}) {
  const cfg = await getConfig();
  let targetUrl;
  try {
    targetUrl = normalizeServerUrl(serverUrl ?? cfg.serverUrl);
  } catch (err) {
    return { ok: false, error: err.message };
  }
  const secret = String(token ?? cfg.token ?? "").trim();
  if (!secret) {
    return { ok: false, error: "No API token configured." };
  }

  try {
    const resp = await fetch(`${targetUrl}/api/ext/snapshot`, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${secret}`,
        Accept: "application/json",
      },
      cache: "no-store",
    });
    if (!resp.ok) {
      return { ok: false, status: resp.status, error: `Snapshot HTTP ${resp.status}` };
    }
    const data = await resp.json();
    const snapshotRecord = {
      items: Array.isArray(data.items) ? data.items : [],
      itemCount: Number(data.item_count ?? data.items?.length ?? 0),
      generatedAt: data.generated_at || new Date().toISOString(),
      syncedAt: Date.now(),
    };
    await ext.storage.local.set({ snapshot: snapshotRecord });
    return {
      ok: true,
      itemCount: snapshotRecord.itemCount,
      generatedAt: snapshotRecord.generatedAt,
      syncedAt: snapshotRecord.syncedAt,
    };
  } catch {
    return { ok: false, error: "Could not sync snapshot while server is offline." };
  }
}

async function pingServer({ serverUrl, token } = {}) {
  const cfg = await getConfig();
  const targetUrl = normalizeServerUrl(serverUrl ?? cfg.serverUrl);
  const secret = String(token ?? cfg.token ?? "").trim();
  if (!secret) {
    return { ok: false, status: 401, error: "No API token configured." };
  }

  try {
    const resp = await fetch(`${targetUrl}/api/ext/ping`, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${secret}`,
        Accept: "application/json",
      },
      cache: "no-store",
    });
    if (resp.status === 401) {
      return { ok: false, status: 401, error: "Invalid or revoked API token." };
    }
    if (!resp.ok) {
      return { ok: false, status: resp.status, error: `Server returned HTTP ${resp.status}.` };
    }
    const data = await resp.json();
    const snap = await syncSnapshot({ serverUrl: targetUrl, token: secret });
    return {
      ok: true,
      status: 200,
      data,
      snapshot: snap.ok ? snap : null,
    };
  } catch {
    return {
      ok: false,
      status: 0,
      error: "Grocery Tracker server is unreachable. Confirm it is running on 127.0.0.1:8000.",
    };
  }
}

async function performLookup(params = {}) {
  const { serverUrl, token } = await getConfig();
  if (!token) {
    return {
      ok: false,
      status: 401,
      error: "Set your TruePriceMemory token in Extension Options first.",
    };
  }

  let url;
  try {
    url = buildLookupUrl(serverUrl, params);
  } catch (err) {
    return { ok: false, status: 0, error: err.message };
  }

  try {
    const resp = await fetch(url, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/json",
      },
      cache: "no-store",
    });
    if (resp.status === 401) {
      return {
        ok: false,
        status: 401,
        error: "Token rejected (401). Generate a new token in Grocery Tracker Settings.",
      };
    }
    if (resp.status === 429) {
      return {
        ok: false,
        status: 429,
        error: "Rate limit reached. Please wait a moment.",
      };
    }
    if (!resp.ok) {
      return { ok: false, status: resp.status, error: `Server error (HTTP ${resp.status}).` };
    }
    const data = await resp.json();
    const record = {
      ok: true,
      offline: false,
      status: 200,
      data,
      params,
      timestamp: Date.now(),
    };
    await ext.storage.local.set({ lastLookup: record });

    // Refresh offline snapshot in the background if missing or older than 30 minutes.
    ext.storage.local.get(["snapshot"]).then((stored) => {
      const syncedAt = stored?.snapshot?.syncedAt || 0;
      if (Date.now() - syncedAt > SNAPSHOT_STALE_MS) {
        syncSnapshot({ serverUrl, token });
      }
    });

    return record;
  } catch {
    const stored = await ext.storage.local.get(["snapshot"]);
    if (stored?.snapshot && Array.isArray(stored.snapshot.items)) {
      const data = matchOfflineSnapshot(stored.snapshot.items, params);
      const record = {
        ok: true,
        offline: true,
        snapshotSyncedAt: stored.snapshot.syncedAt || null,
        snapshotGeneratedAt: stored.snapshot.generatedAt || null,
        status: 200,
        data,
        params,
        timestamp: Date.now(),
      };
      await ext.storage.local.set({ lastLookup: record });
      return record;
    }
    return {
      ok: false,
      status: 0,
      error: "Grocery Tracker is offline and no cached snapshot is stored yet.",
    };
  }
}

function registerContextMenu() {
  if (!ext?.contextMenus) return;
  ext.contextMenus.removeAll(() => {
    ext.contextMenus.create({
      id: CONTEXT_MENU_ID,
      title: 'Look up "%s" in TruePriceMemory',
      contexts: ["selection"],
    });
  });
}

if (ext?.runtime?.onInstalled) {
  ext.runtime.onInstalled.addListener(() => {
    registerContextMenu();
  });
}

if (ext?.runtime?.onStartup) {
  ext.runtime.onStartup.addListener(() => {
    registerContextMenu();
  });
}

if (ext?.contextMenus?.onClicked) {
  ext.contextMenus.onClicked.addListener(async (info, tab) => {
    if (info.menuItemId !== CONTEXT_MENU_ID) return;
    const selectedText = String(info.selectionText || "").trim();
    if (!selectedText) return;

    const store = inferStoreFromUrl(tab?.url || info.pageUrl || "", tab?.title || "");
    const result = await performLookup({ q: selectedText, store });

    if (ext.action?.setBadgeText && tab?.id) {
      const count = result.ok ? result.data?.matches?.length || 0 : 0;
      await ext.action.setBadgeText({
        tabId: tab.id,
        text: result.ok ? (count > 0 ? String(count) : "0") : "!",
      });
      await ext.action.setBadgeBackgroundColor?.({
        tabId: tab.id,
        color: result.ok && count > 0 ? "#4f46e5" : "#64748b",
      });
    }
    if (ext.action?.openPopup) {
      try {
        await ext.action.openPopup();
      } catch {
        // openPopup requires an active user gesture in some browser versions; badge is set either way.
      }
    }
  });
}

if (ext?.tabs?.onRemoved) {
  ext.tabs.onRemoved.addListener((tabId) => {
    tabProducts.delete(tabId);
  });
}

if (ext?.runtime?.onMessage) {
  ext.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (!message || typeof message !== "object") return false;

    if (message.type === "tpm:ping") {
      pingServer(message.payload).then(sendResponse);
      return true;
    }

    if (message.type === "tpm:sync-snapshot") {
      syncSnapshot(message.payload).then(sendResponse);
      return true;
    }

    if (message.type === "tpm:lookup") {
      performLookup(message.payload).then(sendResponse);
      return true;
    }

    if (message.type === "tpm:page-product") {
      const tabId = sender?.tab?.id;
      if (tabId && message.payload) {
        tabProducts.set(tabId, {
          ...message.payload,
          title: message.payload.title || message.payload.q || "",
          updatedAt: Date.now(),
        });
      }
      performLookup(message.payload).then(async (result) => {
        if (ext.action?.setBadgeText && tabId) {
          const count = result.ok ? result.data?.matches?.length || 0 : 0;
          await ext.action.setBadgeText({
            tabId,
            text: result.ok && count > 0 ? String(count) : "",
          });
          if (result.ok && count > 0) {
            await ext.action.setBadgeBackgroundColor?.({
              tabId,
              color: "#4f46e5",
            });
          }
        }
        sendResponse(result);
      });
      return true;
    }

    if (message.type === "tpm:get-state") {
      (async () => {
        const config = await getConfig();
        const stored = await ext.storage.local.get(["lastLookup", "snapshot"]);
        const tabProduct = message.tabId ? tabProducts.get(message.tabId) || null : null;
        const snapshotMeta = stored.snapshot
          ? {
              itemCount: stored.snapshot.itemCount || 0,
              syncedAt: stored.snapshot.syncedAt || null,
              generatedAt: stored.snapshot.generatedAt || null,
            }
          : null;
        sendResponse({
          hasToken: Boolean(config.token),
          serverUrl: config.serverUrl,
          lastLookup: stored.lastLookup || null,
          tabProduct,
          snapshotMeta,
        });
      })();
      return true;
    }

    return false;
  });
}
