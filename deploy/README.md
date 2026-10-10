# Running as a macOS service (launchd)

`com.john.deepseek-web2api.plist` is the LaunchAgent that keeps the proxy up —
it starts at login (`RunAtLoad`) and is restarted if it crashes or exits
(`KeepAlive`). It runs `uvicorn server:app` on `127.0.0.1:8080` from the repo's
own `.venv`, with the repo as the working directory (so it finds `.env` and
`data/accounts.json`). Logs go to `ds2api.log` in the repo.

Install (paths in the plist are absolute — edit them for your setup):

```bash
cp deploy/com.john.deepseek-web2api.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.john.deepseek-web2api.plist
```

Manage it:

```bash
launchctl print  gui/$(id -u)/com.john.deepseek-web2api   # status / pid
launchctl kickstart -k gui/$(id -u)/com.john.deepseek-web2api  # restart
launchctl bootout gui/$(id -u)/com.john.deepseek-web2api   # stop + unload
```
