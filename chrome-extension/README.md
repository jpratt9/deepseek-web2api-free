# DeepSeek → DS2API (Chrome extension)

Grabs your `chat.deepseek.com` credentials and pushes them into the local
DS2API proxy's account pool with a hotkey — no more digging through DevTools.

It reads:
- the live **`Authorization: Bearer` token** (captured from DeepSeek's own API
  calls, with a localStorage fallback), and
- the **full cookie set** for `chat.deepseek.com`, including HttpOnly cookies
  like `cf_clearance` that page scripts can't see (via the `chrome.cookies` API),

then POSTs them to `POST /admin/api/accounts` on your proxy (no auth needed —
the admin login was removed for local use). Repeated pushes upsert the same
account (matched by **label**) instead of creating duplicates.

## Install

1. Open `chrome://extensions`, turn on **Developer mode** (top right).
2. **Load unpacked** → select this `chrome-extension/` folder.
3. (Optional) Set the hotkey at `chrome://extensions/shortcuts` — default is
   **Ctrl+Shift+Y** (**⌘+Shift+Y** on macOS).

## Use

1. Make sure the proxy is running (`http://127.0.0.1:8080` by default).
2. Log into `chat.deepseek.com` and send at least one message (so the token is
   captured).
3. Press the hotkey — or click the toolbar icon and hit **Push now**.
4. The account shows up in the WebUI → **Account Pool**. A ✓ badge on the icon
   means success; click the icon to see the status line.

## Config (popup)

- **Proxy URL** — default `http://127.0.0.1:8080`. Change it if you run the
  proxy on another host/port.
- **Account label** — the account's name in the pool (default `deepseek`).
  Pushes with the same label update that one account.

## Notes

- Everything stays local: creds go only to the Proxy URL you set.
- If a push says "No token yet", reload `chat.deepseek.com` / send a message,
  then retry — the token is captured from a live request.
- Tokens/cookies expire; just press the hotkey again to refresh the account.
