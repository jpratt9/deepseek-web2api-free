const DEFAULTS = { proxyUrl: "http://127.0.0.1:8080", label: "deepseek" };

const $ = (id) => document.getElementById(id);
const proxyEl = $("proxy");
const labelEl = $("label");
const statusEl = $("status");

function renderStatus(text, ok) {
  statusEl.textContent = text || "Ready.";
  statusEl.className = "status" + (ok === true ? " ok" : ok === false ? " err" : "");
}

async function load() {
  const c = await chrome.storage.local.get(["proxyUrl", "label", "lastStatus", "lastOk"]);
  proxyEl.value = c.proxyUrl || DEFAULTS.proxyUrl;
  labelEl.value = c.label || DEFAULTS.label;
  if (c.lastStatus) renderStatus(c.lastStatus, c.lastOk);
}

function save() {
  chrome.storage.local.set({
    proxyUrl: proxyEl.value.trim() || DEFAULTS.proxyUrl,
    label: labelEl.value.trim() || DEFAULTS.label,
  });
}

proxyEl.addEventListener("change", save);
labelEl.addEventListener("change", save);

$("push").addEventListener("click", async () => {
  save();
  renderStatus("Pushing…");
  try {
    const r = await chrome.runtime.sendMessage({ type: "push" });
    if (r) renderStatus(r.status, r.ok);
  } catch (e) {
    renderStatus("Error: " + String((e && e.message) || e), false);
  }
});

$("shortcuts").addEventListener("click", (e) => {
  e.preventDefault();
  chrome.tabs.create({ url: "chrome://extensions/shortcuts" });
});

load();
