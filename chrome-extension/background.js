// DeepSeek → DS2API — service worker.
//
// Two jobs:
//  1. Continuously capture the live `Authorization: Bearer <token>` header that
//     chat.deepseek.com sends on its own API calls (the exact working token).
//  2. On the hotkey (or the popup's "Push now"), read that token + the full
//     cookie jar (including HttpOnly cookies like cf_clearance, which a page
//     script can't see) and upsert them into the local DS2API account pool.

const DEFAULTS = { proxyUrl: "http://127.0.0.1:8080", label: "deepseek" };

// --- 1. capture the live bearer token from DeepSeek's own requests ----------
chrome.webRequest.onBeforeSendHeaders.addListener(
  (details) => {
    const h = (details.requestHeaders || []).find(
      (x) => x.name.toLowerCase() === "authorization",
    );
    if (h && h.value && /^Bearer\s+/i.test(h.value)) {
      const token = h.value.replace(/^Bearer\s+/i, "").trim();
      if (token) chrome.storage.local.set({ capturedToken: token, capturedAt: Date.now() });
    }
  },
  { urls: ["https://chat.deepseek.com/*"] },
  ["requestHeaders", "extraHeaders"],
);

// --- 2. triggers ------------------------------------------------------------
chrome.commands.onCommand.addListener((cmd) => {
  if (cmd === "push-creds") pushCreds();
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "push") {
    pushCreds().then((r) => sendResponse(r));
    return true; // async response
  }
});

// --- helpers ----------------------------------------------------------------
async function getConfig() {
  const c = await chrome.storage.local.get(["proxyUrl", "label"]);
  return {
    proxyUrl: (c.proxyUrl || DEFAULTS.proxyUrl).trim(),
    label: (c.label || DEFAULTS.label).trim() || DEFAULTS.label,
  };
}

async function nextLabel(base, prefix) {
  // The next unused label: prefix, then prefix2, prefix3, … (matches the
  // existing pool so a push never clobbers an account already there).
  const taken = new Set();
  try {
    const r = await fetch(`${base}/admin/api/accounts`);
    if (r.ok) {
      const d = await r.json();
      for (const a of d.accounts || []) taken.add(a.email || "");
    }
  } catch (e) { /* proxy down → fall back to the bare prefix */ }
  if (!taken.has(prefix)) return prefix;
  let n = 2;
  while (taken.has(`${prefix}${n}`)) n++;
  return `${prefix}${n}`;
}

async function getCookieHeader() {
  // Cookies applicable to chat.deepseek.com — mirrors the real Cookie header,
  // HttpOnly cookies included.
  const cookies = await chrome.cookies.getAll({ url: "https://chat.deepseek.com/" });
  return cookies.map((c) => `${c.name}=${c.value}`).join("; ");
}

async function getToken() {
  // The captured header value is the authoritative, known-good token.
  const { capturedToken } = await chrome.storage.local.get("capturedToken");
  if (capturedToken) return capturedToken;
  // Fallback: read it straight out of the page's localStorage.
  const tabs = await chrome.tabs.query({ url: "https://chat.deepseek.com/*" });
  if (!tabs || !tabs[0]) return null;
  try {
    const [res] = await chrome.scripting.executeScript({
      target: { tabId: tabs[0].id },
      func: readTokenFromPage,
    });
    return (res && res.result) || null;
  } catch {
    return null;
  }
}

// Runs in the DeepSeek page's context. Self-contained (no outer references).
function readTokenFromPage() {
  const pick = (v) => {
    if (!v) return null;
    const s = String(v);
    const jwt = s.match(/eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/);
    if (jwt) return jwt[0];
    const t = s.trim();
    if (/^[A-Za-z0-9._-]{24,}$/.test(t)) return t;
    return null;
  };
  try {
    const raw = localStorage.getItem("userToken");
    if (raw) {
      try { const o = JSON.parse(raw); const t = pick(o && (o.value || o.token)); if (t) return t; } catch (e) {}
      const t = pick(raw); if (t) return t;
    }
  } catch (e) {}
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const v = localStorage.getItem(localStorage.key(i));
      const t = pick(v); if (t) return t;
      try { const o = JSON.parse(v); const t2 = pick(o && (o.value || o.token)); if (t2) return t2; } catch (e) {}
    }
  } catch (e) {}
  return null;
}

async function pushCreds() {
  const cfg = await getConfig();
  const base = cfg.proxyUrl.replace(/\/+$/, "");
  try {
    const cookies = await getCookieHeader();
    const token = await getToken();
    if (!token) {
      return flash(false, "No token yet — open chat.deepseek.com, send one message, then retry.");
    }
    if (!cookies) {
      return flash(false, "No cookies — make sure you're logged into chat.deepseek.com.");
    }

    // Pick the next free label (prefix, prefix2, prefix3, …) so each push ADDS
    // a new account instead of overwriting one you already pushed.
    const label = await nextLabel(base, cfg.label);
    const res = await fetch(`${base}/admin/api/accounts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, cookies, email: label }),
    });
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status} ${body.slice(0, 140)}`);
    }
    return flash(true, `Added "${label}" on ${base} @ ${new Date().toLocaleTimeString()}`);
  } catch (e) {
    const msg = String((e && e.message) || e);
    return flash(false, `Failed: ${msg}  (is DS2API running at ${base}?)`);
  }
}

function flash(ok, status) {
  chrome.storage.local.set({ lastStatus: status, lastOk: ok, lastAt: Date.now() });
  try {
    chrome.action.setBadgeBackgroundColor({ color: ok ? "#2e7d58" : "#b23b3b" });
    chrome.action.setBadgeText({ text: ok ? "✓" : "!" });
    setTimeout(() => chrome.action.setBadgeText({ text: "" }), 4000);
  } catch (e) {}
  return { ok, status };
}
