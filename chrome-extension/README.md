# DeepSeek → DS2API (Chrome extension)

Grabs your `chat.deepseek.com` credentials and pushes them into the local
DS2API proxy's account pool with a hotkey — no more digging through DevTools.

It reads:
- the live **`Authorization: Bearer` token** (captured from DeepSeek's own API
  calls, with a localStorage fallback), and
- the **full cookie set** for `chat.deepseek.com`, including HttpOnly cookies
  like `cf_clearance` that page scripts can't see (via the `chrome.cookies` API),

then POSTs them to `POST /admin/api/accounts` on your proxy (no auth needed —
the admin login was removed for local use). Each push **adds a new account**
with an auto-numbered label (`deepseek`, `deepseek2`, `deepseek3`, …) so it
never overwrites a login you already pushed — handy for stacking multiple
DeepSeek accounts in the pool.

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
- **Account label** — the base name in the pool (default `deepseek`). Each push
  adds `deepseek`, then `deepseek2`, `deepseek3`, … so nothing gets overwritten.

## Notes

- Everything stays local: creds go only to the Proxy URL you set.
- If a push says "No token yet", reload `chat.deepseek.com` / send a message,
  then retry — the token is captured from a live request.
- Tokens/cookies expire; just press the hotkey again to refresh the account.
