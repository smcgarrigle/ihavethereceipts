import { DEFAULT_SERVER_URL, normalizeServerUrl } from "../common.js";

const ext = globalThis.browser ?? globalThis.chrome;

const form = document.getElementById("options-form");
const serverUrlInput = document.getElementById("server-url");
const tokenInput = document.getElementById("api-token");
const toggleBtn = document.getElementById("toggle-token-btn");
const statusBanner = document.getElementById("status-banner");
const settingsLink = document.getElementById("settings-link");

function showStatus(kind, text) {
  statusBanner.textContent = text;
  statusBanner.className = `status ${kind}`;
}

async function loadSaved() {
  const stored = await ext.storage.local.get(["serverUrl", "token"]);
  const url = stored.serverUrl || DEFAULT_SERVER_URL;
  serverUrlInput.value = url;
  tokenInput.value = stored.token || "";
  settingsLink.href = `${url}/settings`;
}

toggleBtn.addEventListener("click", () => {
  const isPassword = tokenInput.type === "password";
  tokenInput.type = isPassword ? "text" : "password";
  toggleBtn.textContent = isPassword ? "Hide Token" : "Show Token";
});

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
    showStatus(
      "ok",
      `Connected to ${resp.data.app} v${resp.data.version} at ${normalizedUrl}.`
    );
  } else {
    showStatus("err", resp?.error || "Could not connect to server.");
  }
});

loadSaved();
