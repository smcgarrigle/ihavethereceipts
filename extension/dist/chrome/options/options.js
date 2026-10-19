import { DEFAULT_SERVER_URL, normalizeServerUrl } from "../common.js";

const ext = globalThis.browser ?? globalThis.chrome;

const form = document.getElementById("options-form");
const serverUrlInput = document.getElementById("server-url");
const tokenInput = document.getElementById("api-token");
const toggleBtn = document.getElementById("toggle-token-btn");
const syncBtn = document.getElementById("sync-snapshot-btn");
const statusBanner = document.getElementById("status-banner");
const snapshotStatus = document.getElementById("snapshot-status");
const settingsLink = document.getElementById("settings-link");

function showStatus(kind, text) {
  statusBanner.textContent = text;
  statusBanner.className = `status ${kind}`;
}

function renderSnapshotStatus(snapshot) {
  if (!snapshotStatus) return;
  if (!snapshot || !Number.isFinite(Number(snapshot.itemCount))) {
    snapshotStatus.textContent = "Offline snapshot: not synced yet.";
    return;
  }
  const when = snapshot.syncedAt
    ? new Date(snapshot.syncedAt).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      })
    : "just now";
  snapshotStatus.textContent = `Offline snapshot: ${snapshot.itemCount} items cached (synced ${when}).`;
}

async function loadSaved() {
  const stored = await ext.storage.local.get(["serverUrl", "token", "snapshot"]);
  const url = stored.serverUrl || DEFAULT_SERVER_URL;
  serverUrlInput.value = url;
  tokenInput.value = stored.token || "";
  settingsLink.href = `${url}/settings`;
  renderSnapshotStatus(stored.snapshot || null);
}

toggleBtn.addEventListener("click", () => {
  const isPassword = tokenInput.type === "password";
  tokenInput.type = isPassword ? "text" : "password";
  toggleBtn.textContent = isPassword ? "Hide Token" : "Show Token";
});

if (syncBtn) {
  syncBtn.addEventListener("click", async () => {
    showStatus("ok", "Syncing offline snapshot…");
    const resp = await ext.runtime.sendMessage({
      type: "tpm:sync-snapshot",
      payload: {
        serverUrl: serverUrlInput.value,
        token: tokenInput.value.trim(),
      },
    });
    if (resp?.ok) {
      renderSnapshotStatus(resp);
      showStatus("ok", `Synced ${resp.itemCount} items for offline lookup.`);
    } else {
      showStatus("err", resp?.error || "Could not sync offline snapshot.");
    }
  });
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  let normalizedUrl;
  try {
    normalizedUrl = normalizeServerUrl(serverUrlInput.value);
  } catch (err) {
    showStatus("err", err.message);
    return;
  }

  const token = tokenInput.value.trim();
  if (!token) {
    showStatus("err", "Paste a tpm_... token from Grocery Tracker Settings.");
    return;
  }

  serverUrlInput.value = normalizedUrl;
  settingsLink.href = `${normalizedUrl}/settings`;
  await ext.storage.local.set({ serverUrl: normalizedUrl, token });

  showStatus("ok", "Testing connection…");
  const resp = await ext.runtime.sendMessage({
    type: "tpm:ping",
    payload: { serverUrl: normalizedUrl, token },
  });

  if (resp?.ok) {
    if (resp.snapshot) {
      renderSnapshotStatus(resp.snapshot);
    }
    const snapText = resp.snapshot
      ? ` (${resp.snapshot.itemCount} items cached for offline lookup)`
      : "";
    showStatus(
      "ok",
      `Connected to ${resp.data.app} v${resp.data.version} at ${normalizedUrl}${snapText}.`
    );
  } else {
    showStatus("err", resp?.error || "Could not connect to server.");
  }
});

loadSaved();
