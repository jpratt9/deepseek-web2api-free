# AGENTS.md — DeepSeek Chat API Proxy (Preview)

> This document is for AI agents who will maintain this project later. It fully explains the project's implementation principles, protocol details, code architecture, and known issues. **Please read the whole document before making any changes.**

## Current account configuration rules

- Account credentials are configured only through the WebUI account pool or `data/accounts.json`; WebUI changes are persisted to that JSON file.
- `DEEPSEEK_TOKEN`, `DEEPSEEK_COOKIES`, `DEEPSEEK_EMAIL`, `DEEPSEEK_PROXY` in `.env`, and their numbered forms, are no longer read; when the pool is empty there is no environment-variable fallback.
- The version notes below preserve the implementation history at the time; the `.env` account fallback they once described has since been removed.

---

## v3.3.4 (2026-09-10): Anthropic non-streaming error mapping

- The `/v1/messages` non-streaming path now maps upstream rate limiting to 429, and empty responses and protocol hint errors to 502, consistent with the OpenAI endpoint; added regression tests and wired them into CI.

## v3.3.3 (2026-09-10): session isolation and account-binding fix

- `ChatSession` now records the `account_id` that created the upstream session. Continuations prefer that account; if it is busy or unavailable, a new session is started safely, never handing one account's `chat_session_id` / `parent_message_id` to another account.
- The session cache accepts only explicit session identifiers: `X-Conversation-Id`, OpenAI's top-level `user`, or Anthropic `metadata.user_id`. The cache key is also isolated per caller (hash of the API key; the client IP when unauthenticated). The "first-message summary" fallback was removed to avoid crosstalk when different users share the same opening line.

---

## v3.0.0 → v3.3.2 change summary

### v3.3.2 (2026-09-05): WebUI request-trend chart fix (stats history sampling AttributeError)

- **Merged PR #14**: `stats_history.StatsHistory.snapshot()` read an `avg_latency_ms` attribute that does not exist on `StatsSnapshot` → every snapshot threw `AttributeError`, swallowed silently by the sampler thread's `except Exception: pass` → `/admin/api/history` always returned `points: []` from process start. Fixed to the same self-computed average as the `/admin/api/stats` endpoint: `total_latency_ms / total_requests` (0.0 when there are zero requests) (see [docs/release-notes/v3.3.2.md](docs/release-notes/v3.3.2.md)).
- **Tests**: added `tests/test_stats_history.py` (4 cases: normal values / no divide-by-zero on zero requests / strict-object regression — snapshot may touch only fields that really exist / max_points truncation).

### v3.3.1 (2026-08-11): anti-flooding hardening + bilingual docs

- **Merged PR #11 (anti account-mute)**: upstream concurrency cap `DEEPSEEK_MAX_CONCURRENCY` (default 2) + incremental (delta) prompt + mute detection (`UserMutedError` → 429) + parent cleanup on retry + `SESSION_CACHE_TTL` default 600 → 1800 (see [docs/release-notes/v3.3.1.md](docs/release-notes/v3.3.1.md)).
- **Docs**: added `README_en.md`, a complete English version + a bilingual language-switcher link at the top; removed the version-log block at the top of the README (changelog lives in docs/release-notes/); added "Non-interactive account-pool configuration" to README/AGENTS.md (accounts.json schema + automation configuration checklist).

---

## v3.0.0 → v3.2.4 change summary

### v3.2.4 (2026-08-11): upstream concurrency cap + incremental prompt (anti history-flood / anti-mute)

- **Concurrency cap**: `DEEPSEEK_MAX_CONCURRENCY` (default `2`) globally limits in-flight upstream requests (across accounts); requests over the limit queue and wait instead of getting a 503 (`_UPSTREAM_LIMITER` `BoundedSemaphore`, acquired in `_acquire()` before `pool.acquire()`, released idempotently by `AcquiredAccount.release()`). Coding agents (opencode/Claude Code) spawn multiple parallel sub-agents that previously flooded the upstream concurrently and triggered account mutes.
- **Incremental prompt (delta)**: `ChatSession.sent_prompt` records the full prompt actually sent last round; `AcquiredAccount.prepare_prompt()` does a prefix comparison against the full history the client re-sends — when the history is a continuation of the previous round, only the **newly added tail** is sent upstream (context is maintained server-side by the parent chain); an exact repeat is treated as a retry (re-send) of the same round; a divergent history invalidates the cache and starts a new session. Previously every request re-sent the entire history, and each message in a DeepSeek session embedded all prior rounds (quadratic blow-up, with a strong automation signature — a major cause of account mutes).
- **Mute detection**: the upstream returns account-level penalties as a 200 + plain JSON `{"data":{"biz_code":5,"biz_msg":"user is muted","mute_until":...}}` (not SSE; old code parsed it as an "empty response"). `UserMutedError` (a `RateLimitError` subclass) is detected on both the streaming and non-streaming paths and thrown immediately (skipping backoff retries), mapped to 429 with the unmute time.
- **Retry with cleanup**: on a rate-limit/empty-response retry with a new session, the old session's `parent_message_id` is no longer carried over (an invalid parent in the new session would cause the upstream to return empty again).
- **SESSION_CACHE_TTL default 600 → 1800**: long coding sessions (an agent idle 10+ minutes) are no longer frequently forced to create a new upstream session.
- Full list: `docs/release-notes/v3.2.4.md`

### v3.2.3 (2026-08-08): multi-turn session reuse fix (parent-chain maintenance)

- **Root cause**: a v3.2.2 leftover — when reusing a session across turns in the same mode, the cached `parent_message_id` was not updated per turn (always `0`), so the second request sent `parent_message_id=0` → the upstream returned an empty response, self-healing only after one failure.
- **Fix**: the adapter extracts `response_message_id` from the SSE `event: ready` frame (non-streaming also accepts `v.response.message_id`) and returns it to the server via the new `ready_out` callback parameter; `AcquiredAccount.record_message_id()` writes the real message_id + the session actually used back into `SESSION_CACHE` (and syncs `chat_session_id` when retrying with a new session), and fixes the issue where `create_session()` did not save the `_cached_session` reference, which invalidated the record.
- **Wiring points**: all 4 paths wired (OpenAI/Anthropic × streaming/non-streaming), tool-call branches record too.
- Full list: `docs/release-notes/v3.2.3.md`

### v3.2.1 (2026-08-03): empty-response root-cause fix

- **Root cause**: when requests are too frequent the upstream returns HTTP 200 + an SSE `event: hint` (`type=error`, `finish_reason=rate_limit_reached`, "messages sent too frequently, please retry later") with **no content tokens**; the adapter did not previously parse `hint` events → rate limiting was returned as "empty content".
- **Fix**: added `RateLimitError`/`UpstreamHintError`, with non-streaming `_scan_hint_errors()` + inline hint detection on the streaming path (mirroring toast); the `server` maps these to **429** (rate limit) / 502 (other hint errors).
- Full list: `docs/release-notes/v3.2.1.md`

### v3.2.2 (2026-08-03): rate-limit adaptivity + hif sending + test coverage + session-cache fix

- **Upstream rate-limit adaptivity**: `RateLimitError` backoff retries (`DEEPSEEK_RATE_LIMIT_RETRY_DELAYS` default `5,15`, new session after each backoff); `DEEPSEEK_JITTER_SECS` default `0.4` (reduces the chance of tripping rate limiting).
- **hif signature header sending**: `_HifProvider` fetches `hif-leim/hif-dliq.deepseek.com/query` (`data.biz_data.value`, cached per `x-hif-ttl`, default 600s); completion requests attach `X-Hif-Leim/Dliq` (create_session does not); on failure it silently degrades (no header added).
- **Test coverage**: `tests/test_adapter.py` (15 cases: hint/toast/empty-response retry/backoff/hif) + `tests/test_account_pool.py` (10 cases: env fallback/empty pool/read-only protection/persistence), 81 tests total.
- Streaming toast/hint detection fix: the upstream error data is a top-level dict (not wrapped in `v`); both are checked.
- **SESSION_CACHE mode isolation**: the cache key distinguishes streaming/non-streaming (`stream:`/`nonstream:`), fixing "a session created in streaming mode reused by non-streaming → empty response"; on rate limit/empty response the cache is `invalidate`d (self-heals after one failure).
- **Known leftover → fixed (v3.2.3)**: the empty response caused by a wrong parent on the second request when reusing a session across turns in the same mode, resolved by extracting `response_message_id` from the SSE `ready` event to maintain the parent chain (see the v3.2.3 summary).

### v3.2.0 (2026-08-02): maintenance release

- **start.bat rewrite**: auto-locate Python 3.10+, detect/create a virtualenv (`.venv`/`venv`/`env`), `pip install --dry-run` to verify dependencies and auto-install, auto `npm` build when the WebUI dist is missing (`WEBUI_REBUILD=1` forces a rebuild), print the access URL before startup and auto-open the browser after 3s by default (`WEBUI_OPEN=0` skips), and on a port conflict kill only this project's processes (PowerShell `Get-CimInstance` reads the command line, replacing the deprecated `wmic`; GBK+CRLF encoding).
- **WebUI**: static-asset 404 fix (vite `base: '/webui/'` + router `basename: '/webui'`), 7 bug fixes and UI polish, Playground rewrite (parameters mirror what the backend actually forwards, the ineffective temperature slider removed, `reasoning_content` visualized), quick/expert model modes (`MODEL_ROUTES` enabled by default).
- **Auth**: `/v1/*` accepts a valid admin-session token (`verify_admin_token`).
- **Account pool**: env credentials changed to a **read-only fallback when the pool is empty** (`_env_fallback`, panel accounts take priority; no longer preloaded into the pool).
- **Upstream empty-response hardening**: `UpstreamEmptyError` + 1 retry with a new session + 502/error frame.
- **Adapter**: `X-Client-Version` 2.0.0 → 2.3.0, removed the obsolete `X-App-Version` (HAR comparison confirmed the browser no longer sends it).
- **hif signature headers** (reverse-engineering notes): the browser sends `x-hif-leim`/`x-hif-dliq` (values from `hif-leim/hif-dliq.deepseek.com/query`, TTL 600s, localStorage cache); since v3.2.2 the adapter auto-fetches and sends them via `_HifProvider` (silent degradation on failure, see 7.13).
- **Known environment facts**: `wmic` was removed in Win11 24H2+; the `timeout` command conflicts with Git Bash's GNU coreutils (the script uses `ping -n 2` for delays).
- Full list: `docs/release-notes/v3.2.0.md`

### v3.0.0 (2026-06): React WebUI rewrite

- The admin panel was rewritten from vanilla JS into a **Vite + React 18 + TypeScript + shadcn/ui** SPA (`webui-new/`), with 6 pages (Login / Overview / Account Pool / Playground / Settings / 404).
- Added `stats_history.py` (30s snapshot rolling window), `GET /admin/api/history`, `GET /admin/api/env`.
- The WebUI artifacts live in `webui-new/dist/`, served by `server.py` under `/webui/*`; the old `webui/` was removed.
- **Build requirement**: vite `base: '/webui/'` + react-router `basename: '/webui'`; missing either causes a 404 white screen for assets.

---

## v2.2.0 change summary (2026-06)

New modules: `logger.py`, `crypto.py`, `ip_utils.py`, `token_counter.py`,
`rate_limiter.py`, `model_router.py`, `session_cache.py`.

Main changes:

- **Security**: default `HOST=127.0.0.1`; `SystemExit(2)` when starting on a public bind with the default password; structured JSON logs; optional Fernet encryption for `data/accounts.json` (transparent migration on startup); stricter CORS (empty = same-origin); XFF allowlist (`TRUSTED_PROXIES`); security response headers.
- **Bugs**: `adapter.chat()` now returns a `(content, thinking)` tuple; `anthropic_format.build_nonstream_response` takes `thinking_text`; `StreamSieve` switched to iterative draining, the `feed("")` recursion replaced with a `while`, a hard 1 MB cap on the capture buffer (configurable via `DSML_MAX_BUFFER_BYTES`); accounts auto-recover via a background `check_health` after reaching 3 errors.
- **New features**: `MODEL_ROUTES` model routing; `SESSION_CACHE_TTL` multi-turn sessions (OpenAI `X-Conversation-Id` header / Anthropic `metadata.user_id`; older versions used a message-summary fallback); `CLIENT_RPM_PER_KEY` / `CLIENT_RPM_PER_IP` dual-dimension sliding-window rate limiting; the `usage` field returns real token counts (tiktoken cl100k_base, with a character heuristic when missing); `/admin/api/stats` gains p50/p95/p99 + success rate.
- **Engineering**: `tests/test_*.py` with 56 pytest cases; CI matrix (3.10/3.11/3.12); SSE error frames (the OpenAI stream sends `data: {"error":...}` then `data: [DONE]` at the end) instead of raising 500 directly.

---

## Table of contents

1. [Project Overview](#1-project-overview)
2. [Directory Structure](#2-directory-structure)
3. [Core Data Flow](#3-core-data-flow)
4. [PoW Anti-Scraping Mechanism](#4-pow-anti-scraping-mechanism)
5. [Session Management](#5-session-management)
6. [SSE Protocol Format](#6-sse-protocol-format)
7. [MODE / THINKING / SEARCH Control System](#7-mode--thinking--search-control-system)
8. [Tool Calls (DSML)](#8-tool-calls-dsml)
9. [StreamSieve Streaming Sieve Engine](#9-streamsieve-streaming-sieve-engine)
10. [OpenAI Compatibility Layer](#10-openai-compatibility-layer)
11. [Anthropic Compatibility Layer](#11-anthropic-compatibility-layer)
12. [Multi-turn Conversations and Message Assembly](#12-multi-turn-conversations-and-message-assembly)
13. [ContentPart Support](#13-contentpart-support)
14. [Configuration System](#14-configuration-system)
15. [Account Pool (AccountPool)](#15-account-pool-accountpool)
16. [Admin Backend (Admin API)](#16-admin-backend-admin-api)
17. [Key Algorithm Details](#17-key-algorithm-details)
18. [Known Limitations and Edge Cases](#18-known-limitations-and-edge-cases)
19. [Common Debugging Methods](#19-common-debugging-methods)
20. [Protocol Change Warnings](#20-protocol-change-warnings)

---

## 1. Project Overview

This project reverse-proxies the DeepSeek Chat web app (https://chat.deepseek.com) as an OpenAI-compatible API.

### 1.1 Problems it solves

- DeepSeek's official API is paid and restricted for users outside mainland China.
- The DeepSeek Chat web app is free but uses a private protocol, incompatible with the OpenAI SDK.
- The web app has a PoW (Proof of Work) anti-scraping mechanism that must be solved automatically.
- DeepSeek offers two conversation capabilities, "quick mode" and "expert mode", whose interface behaviors differ.

### 1.2 Core capabilities

| Capability | Status | Notes |
|------|------|------|
| OpenAI-compatible API | ✅ | `/v1/chat/completions`, `/v1/models`, `/health` |
| Anthropic-compatible API | ✅ | `/v1/messages` — Anthropic Claude API format |
| Streaming output (SSE) | ✅ | OpenAI chunk format + Anthropic SSE format |
| Non-streaming output | ✅ | Full response |
| Multi-turn conversation | ✅ | The client manages context via the messages array |
| Normal conversation | ✅ | Quick mode |
| Expert mode | ✅ | DeepSeek reasoning model, with thinking tokens |
| Tool calls | ✅ | Based on DSML prompt injection (not native) |
| ContentPart arrays | ✅ | content supports str and array formats |
| PoW auto-solve | ✅ | Local WASM solving, 0.1-0.3s |
| Session management | ✅ | A new DeepSeek session per request |
| Web search | ⚠️ | Parameter is passed through; behavior depends on the DeepSeek server |
| MODE env-var control | ✅ | Force a mode via `.env`: `auto`/`quick`/`expert` |
| THINKING env-var control | ✅ | Force thinking via `.env`: `auto`/`enabled`/`disabled` |
| SEARCH env-var control | ✅ | Force web search via `.env`: `auto`/`enabled`/`disabled` |
| model_type decoupled from thinking_enabled | ✅ | Independent; all 4 combinations valid |
| finish_reason SSE end frame | ✅ | Streaming responses send `delta: {}, finish_reason: "stop"` at the end |

### 1.3 Project version

- Current mainline: `v3.3.2` (2026-09) — core features + tool calls + expert mode + web search + React WebUI admin panel + upstream rate-limit hint parsing + multi-turn reuse (parent chain + incremental prompt) + upstream concurrency cap + stats history-sampling fix.
- Since v3.0.0 the open-source and preview editions are merged into a single mainline, with no separate `--pre` branch.

---

## 2. Directory Structure

```
deepseek-web2api-free\
├── server.py              # FastAPI entry point (routing, request models, SSE assembly)
├── adapter.py             # DeepSeek API adapter (PoW, sessions, SSE parsing)
├── anthropic_format.py    # Anthropic /v1/messages format conversion layer
├── account_pool.py        # Multi-account pool management (CRUD, state tracking, round-robin, health checks)
├── admin.py               # Admin backend API (password auth, request stats, account-pool management)
├── tool_dsml.py           # DSML format parser (tool-call protocol)
├── tool_sieve.py          # Streaming sieve engine (real-time detection of tool-call tags)
├── sha3_wasm_bg.wasm      # PoW hash engine WASM binary
├── start.bat              # Windows one-click launcher (auto venv/deps/WebUI/open browser)
├── webui-new/             # Admin panel frontend (v3.0.0+, React SPA, needs an npm build)
│   └── dist/              #   build artifacts (gitignored), served by server.py under /webui/*
├── .env                   # Environment config (contains TOKEN/COOKIE, not committed)
├── .env.example           # Config template (committed to the repo)
├── requirements.txt       # Python dependencies
├── README.md              # User documentation
└── AGENTS.md              # This file
```

### 2.1 File details

#### Core modules

| File | Responsibility | Not responsible for |
|------|------|--------|
| `server.py` | HTTP routing, request/response models, OpenAI format assembly, tool-call coordination | PoW solving, native SSE parsing |
| `adapter.py` | Communicating with the DeepSeek API, PoW solving, SSE stream parsing, session creation | HTTP routing, OpenAI/Anthropic formats |
| `anthropic_format.py` | Anthropic `/v1/messages` request parsing, response assembly, SSE generation | DeepSeek protocol, HTTP routing |
| `account_pool.py` | Multi-account CRUD, state tracking (idle/busy/error), round-robin allocation, health check/relogin | HTTP routing, DeepSeek protocol |
| `admin.py` | Admin backend API endpoints (password auth, stats queries, account-pool CRUD, relogin trigger) | Frontend rendering, DeepSeek protocol |
| `tool_dsml.py` | DSML XML parsing and generation, tool-prompt building | Streaming detection, HTTP |
| `tool_sieve.py` | Real-time detection of DSML tool-call tags in streaming text | Protocol parsing, HTTP |

**Core principle:** `adapter.py`'s output is a "raw token stream" (str or dict); `server.py` and `anthropic_format.py` each wrap it into a specific API format. `adapter.py` knows nothing about any API format.

#### Supporting files

| File | Purpose |
|------|------|
| `sha3_wasm_bg.wasm` | PoW hash engine WASM binary, extracted from DeepSeek's frontend JavaScript. Loaded via `wasmtime`, exports `wasm_solve` and others. Its version is tied to DeepSeek frontend releases. |
| `start.bat` | Windows one-click launcher (GBK encoding + CRLF, do not change the encoding). Flow: locate Python 3.10+ → detect/create a virtualenv (`.venv`/`venv`/`env`) → `pip install --dry-run` to verify dependencies (auto-install if missing) → auto `npm` build when the WebUI dist is missing → port check (kills only this project's processes whose command line matches `uvicorn`/`server:app`/`server.py`/`ds2api`; refuses to kill others and warns) → print the access URL and auto-open the browser after 3s by default (`WEBUI_OPEN=0` skips). Supports `PORT`/`HOST` environment-variable overrides. |
| `webui-new/` | Admin panel frontend (v3.0.0+, Vite + React 18 + TypeScript + shadcn/ui SPA). The source build artifacts are in `webui-new/dist/` (gitignored), served by `server.py` under `/webui/*`. **Must** be built with `base: '/webui/'` + react-router `basename: '/webui'`, otherwise assets 404. The old `webui/` (vanilla) was removed. |
| `requirements.txt` | Python dependency declarations. Key version requirements are in the table below. |
| `.env.example` | Environment config template. Copy to `.env` and fill in credentials. Committed to the repo but contains no sensitive info. |

**Dependency version notes:**

| Package | Minimum version | Purpose | Notes |
|---|---------|------|------|
| `fastapi` | 0.100.0 | Web framework | 0.100+ supports Pydantic v2 |
| `uvicorn` | 0.20.0 | ASGI server | 0.20+ supports lifespan |
| `httpx` | 0.24.0 | HTTP client | 0.24+ fixes a critical connection-pool bug |
| `wasmtime` | 14.0.0 | WASM runtime | 14.0+ is the first version with stable Windows support |
| `python-dotenv` | 1.0.0 | .env loading | 1.0+ behavior is stable |

### 2.2 Development environment setup

```bash
# 1. Clone / enter the project directory
cd deepseek-web2api-free

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure credentials (obtained from the browser DevTools)
copy .env.example .env
# Add an account in the WebUI "Account Pool", or write it into data/accounts.json; account credentials do not go in .env

# 4. Start the service
python server.py
# or
start.bat

# 5. Test
curl http://localhost:8080/health
```

**Hot-reload development (recommended):**
```bash
uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080} --reload
```
`--reload` restarts automatically on file changes, but note it does not clean up `__pycache__` (see §18.5).

### 2.3 Preview vs open-source edition differences

> **Merged since v3.0.0**: the comparison below is for historical reference only. The current mainline has all capabilities of both columns (OpenAI + Anthropic + expert mode + web search + tool calls + React WebUI).

| Dimension | Open-source (`v2.0.0`) | Preview (`v2.2.0-pre`) |
|------|-------------------|----------------------|
| `adapter.py` request body | Basic fields: `chat_session_id`, `prompt`, `ref_file_ids`, `stream` | Added: `parent_message_id`, `model_type`, `thinking_enabled`, `search_enabled`, `preempt` |
| Request headers | `X-App-Version: 0.0.1` | `X-App-Version: 20241129.1` + 5 extra version headers |
| Session creation | Only handles the `biz_data.id` format | Dual-format compatible (`id` or `chat_session.id`) |
| `chat()` | Only parses `response/content APPEND` | Full fragment state machine supporting both modes |
| `chat_stream()` | Simple token pass-through | Fragment state machine + `__type: "thinking"` dict output |
| `_msg_counters` | None | Added, tracks `parent_message_id` |
| `httpx.Client` timeout | 60s | 120s |
| server.py endpoints | Standard OpenAI | Same + `thinking_mode`, `search_enabled` params |
| SSE output | `content` delta | Same + `reasoning_content` delta + `finish_reason: "stop"` end frame |
| MODE env var | None | `auto`/`quick`/`expert`, configured via `.env` |
| THINKING env var | None | `auto`/`enabled`/`disabled`, configured via `.env` |
| SEARCH env var | None | `auto`/`enabled`/`disabled`, configured via `.env` |
| PORT env var | None | Configurable listen port (default 8080), via `.env` or env var |
| model_type control | Bound to thinking_enabled | Fully decoupled, controlled independently by MODE |
| WASM thread safety | Lockless | `threading.Lock` protects concurrent Store access |

---

## 3. Core Data Flow

### 3.1 Full request path

```
Client (OpenAI SDK)
  │  POST /v1/chat/completions  (OpenAI-format JSON)
  ▼
server.py: chat_completions()
  │  _build_prompt() → concatenate messages into plain text
  │  if tools present → build_dsml_tool_prompt() → inject into the system message
  ▼
adapter.py: create_session()
  │  POST /api/v0/chat/create_pow_challenge → get challenge
  │  WASM solve the PoW nonce
  │  POST /api/v0/chat_session/create → get session_id
  ▼
adapter.py: chat() or chat_stream()
  │  POST /api/v0/chat/completion (with PoW header + request body)
  │  carries thinking_enabled, search_enabled, model_type, preempt, etc.
  ▼
  SSE stream parsing (line by line)
  │  handle event: ready → extract request_message_id / response_message_id
  │  handle data: {"v": {"response": {...}}} → first response event
  │  handle data: {"p":"response/fragments/-1/content","o":"APPEND","v":"..."}
  │  handle data: {"v":"token"} → plain token event
  │  handle data: {"p":"response/status"} → status change
  ▼
server.py: event_stream() / _handle_nonstream()
  │  adapter yields → str (plain token) or dict (control/thinking/status)
  │  StreamSieve sieves out tool calls
  │  non-streaming → assemble a full JSON response
  │  streaming → yield OpenAI SSE chunks
  ▼
Client receives an OpenAI-format response
```

### 3.2 Data-format conversion

```
Client sends → OpenAI JSON → server.py turns it into a plain-text prompt
↓
adapter.py sends → DeepSeek SSE → adapter.py parses into a token stream
↓
server.py receives → token stream → assembles OpenAI SSE chunks
↓
Client receives → OpenAI JSON
```

---

## 4. PoW Anti-Scraping Mechanism

### 4.1 Principle

DeepSeek Chat's API uses Proof of Work to prevent abuse. A hash puzzle must be solved before each request.

**Constraints:**
- A challenge has an `expire_at` (Unix timestamp) and is unusable after expiry.
- Each challenge is valid only for the specified `target_path`.
- Difficulty is controlled by the `difficulty` parameter (float; larger is harder).
- A signature-verification mechanism ensures the challenge is not tampered with.

### 4.2 Communication flow

```
1. POST /api/v0/chat/create_pow_challenge
   → request body: {"target_path": "/api/v0/chat/completion"}
   → response body: {
       "data": {
         "biz_data": {
           "challenge": {
             "algorithm": "DeepSeekHashV1",
             "challenge": "53251cf4a7b50ee99952f509374be35b",
             "salt": "ca1264f7b684cbfb7c1a",
             "signature": "33503f082bfd15492d17755c3781ba1b...",
             "difficulty": 262140,
             "expire_at": 1778077771,
             "target_path": "/api/v0/chat/completion"
           }
         }
       }
     }

2. WASM solve the nonce
   - Input: challenge, salt, expire_at, difficulty
   - Output: nonce (int) — a value satisfying the difficulty condition

3. Construct the PoW token
   → base64(json({"algorithm":"DeepSeekHashV1","challenge":...,"salt":...,"answer":<nonce>,"signature":...,"target_path":...}))
   → put into the request header: X-DS-PoW-Response
```

### 4.3 WASM solver (`_WASMSolver`)

`_WASMSolver` wraps the wasmtime runtime and loads DeepSeek's official WASM binary.

**WASM exported functions:**
| Function | Parameters | Notes |
|------|------|------|
| `wasm_solve` | (stack_ptr, chal_ptr, chal_len, prefix_ptr, prefix_len, difficulty) | Core solver function |
| `memory` | — | WASM linear memory |
| `__wbindgen_add_to_stack_pointer` | offset | WASM stack-pointer adjustment |
| `__wbindgen_export_0` | (len, align) → ptr | WASM memory allocation (malloc) |
| `__wbindgen_export_1` | (ptr, old_len, new_len, align) → ptr | WASM memory reallocation (realloc) |
| `__wbindgen_export_2` | (ptr, len, align) | WASM memory free |

**Exported-function verification:** the signatures of the three wasm-bindgen exports are verified programmatically via the wasmtime API:
- `export_0` (malloc): 2 i32 params → returns i32 (ptr)
- `export_1` (realloc): 4 i32 params → returns i32 (ptr)
- `export_2` (free): 3 i32 params → no return value (void)

**Memory management:** `_encode()` allocates WASM memory via `malloc` on each call, recording allocations in the `_allocations` list. `solve()`'s `finally` block frees all allocations via `__wbindgen_export_2`, ensuring no memory leak even if solving fails.

**Thread safety:** a `threading.Lock` protects the `solve()` method. The WASM `Store` instance cannot be shared across threads, but the lock ensures only one thread operates the `Store` at a time. Under FastAPI's multithreaded ASGI mode (e.g. with multiple uvicorn workers), each worker has its own `DeepSeekAdapter` and `_WASMSolver` instance, which do not interfere.

**Solving algorithm (`solve` method):**
```
prefix = salt + "_" + expire_at + "_"
stack_ptr = add_to_stack(-16)         // allocate stack space for the return value
chal_ptr, chal_len = encode(challenge) // write challenge into WASM memory
prefix_ptr, prefix_len = encode(prefix) // write prefix into WASM memory
wasm_solve(stack_ptr, chal_ptr, chal_len, prefix_ptr, prefix_len, difficulty)
// read the result from the stack:
//   bytes[stack_ptr:stack_ptr+4] → success flag (0=failure)
//   bytes[stack_ptr+8:stack_ptr+16] → nonce (f64)
add_to_stack(16)                       // restore the stack pointer
```

**Crash safety:** when WASM solving fails (`ret == 0`) a `PoWError` is raised, and the caller must retry the whole flow.

### 4.4 Performance

- A single solve takes about 0.1-0.3s (depending on difficulty).
- The `_WASMSolver` instance is lazily loaded and reused (a singleton) by `DeepSeekAdapter`.
- The WASM `Store` instance cannot be shared across threads, but this project runs single-threaded.

### 4.5 Limitations

- The algorithm is DeepSeek's custom `DeepSeekHashV1` (a modified Keccak/SHA3).
- The WASM binary `sha3_wasm_bg.wasm` is extracted from DeepSeek's frontend and may change as the frontend updates.
- In some cases the challenge may come back empty or with a changed format, requiring error handling in `_get_challenge`.

---

## 5. Session Management

### 5.1 Design decision: stateless

**Core decision:** every API request creates a brand-new DeepSeek session, and no context is kept after the request ends.

**Reasons:**
- Aligns with OpenAI API behavior: the client manages context via the full `messages` array.
- Simplifies server-side state: no need to handle session expiry or concurrency conflicts.
- DeepSeek sessions have a TTL (about 259200 seconds / 3 days); keeping them alive adds complexity.

### 5.2 Session creation

```python
# adapter.py
def create_session(self) -> str:
    headers = self._pow_headers("/api/v0/chat/completion")
    resp = self._client.post(
        f"{BASE_URL}/api/v0/chat_session/create",
        json={"target_path": "/api/v0/chat/completion"},
        headers=headers,
    )
    data = resp.json()
    # The response format has two shapes (depending on X-App-Version):
    #   V0.0.1: biz_data.id
    #   V20241129.1: biz_data.chat_session.id
```

**Response-format compatibility** (historical observation: early on, different `X-App-Version` values made create_session return two formats; the current adapter's `create_session()` is compatible with both, see 5.2):

Old version header (`X-App-Version: 0.0.1`):
```json
{"data": {"biz_data": {"id": "session-uuid"}}}
```

New version header (`X-App-Version: 20241129.1`):
```json
{"data": {"biz_data": {"chat_session": {"id": "session-uuid", "model_type": "default", ...}}}}
```

### 5.3 Session storage

```python
# server.py — in-memory dict
_sessions: dict[str, str] = {}
# key:   proxy session UUID (generated by server.py)
# value: DeepSeek session ID (returned by adapter.create_session())
```

`_get_session()` generates a proxy session ID, calls the adapter to create a real session, and builds the mapping.
`_get_ds_session()` looks up the real session by proxy session ID.

### 5.4 Message-ID tracking

For expert mode, each message within a session needs an incrementing `parent_message_id`.

```python
# adapter.py
self._msg_counters: dict[str, int] = {}  # key: session_id, value: count
```

- Incremented on each `_send_completion` call.
- First request: `parent_message_id: null`.
- Later requests: `parent_message_id: 1, 2, 3...`.

**Note:** under the current session-per-request design, `parent_message_id` is always `null` (each is the first message of a new session). But the incrementing logic is kept to support future session reuse. If sessions are reused in the future, `parent_message_id` becomes required — the DeepSeek server uses it to correlate context.

### 5.5 Session storage strategy

The current `_sessions` uses a **simple in-memory dict**:

```python
# server.py
_sessions: dict[str, str] = {}
```

Each request creates a new session (`_get_session()`), and the key/value pair stays in the dict. TTL-based auto-cleanup was once attempted but **deliberately not implemented**, for these reasons:
- Under the session-per-request design, each request's lifecycle is very short and the session is not reused.
- The DeepSeek server's session TTL is about 3 days (259200s); stale session IDs cause no real harm.
- A Python dict is memory-efficient enough for normal loads (about 150MB for 1M requests).
- Cleanup logic adds code complexity and does not help correctness.

---



## 6. SSE Protocol Format

### 6.1 DeepSeek custom SSE

DeepSeek Chat uses a custom SSE format (not the standard OpenAI SSE). Each data line looks like:

```
event: ready   ← optional event type
data: {...}    ← JSON data
```

**Core data structures:**

Events are transmitted as JSON on `data:` lines; common shapes:

```
A. Plain token:     {"v": "Hello"}
B. Operation event: {"p": "response/content", "o": "APPEND", "v": "World"}
C. Response metadata: {"v": {"response": {"message_id": 4, ...}}}
D. Status change:   {"p": "response/status", "o": "SET", "v": "FINISHED"}
E. Batch update:    {"p": "response", "o": "BATCH", "v": [...]}
F. Ready event:     {"request_message_id": 1, "response_message_id": 2, "model_type": "expert"}
```

### 6.2 Event types in detail

#### type A: plain token event
```json
{"v": "Hello"}
```
- No `p` or `o` field.
- `v` is a string → appended to the current fragment's content.
- In quick mode this is equivalent to normal reply content.
- In expert mode its assignment is decided by the current `frag_type` state.

#### type B: operation-path event
```json
{"p": "response/content", "o": "APPEND", "v": "World"}
```
- `p`: path (analogous to a filesystem path)
- `o`: operation (APPEND/SET/BATCH)
- `v`: value

Common path/operation combinations:

| `p` | `o` | `v` type | Meaning |
|-----|-----|---------|------|
| `response/content` | `APPEND` | string | quick-mode content append |
| `response/fragments/-1/content` | `APPEND` | string | expert-mode current-fragment content append |
| `response/fragments/-1/content` | — | string | same as above when there is no operation field |
| `response/fragments/-1/elapsed_secs` | `SET` | number | fragment elapsed time |
| `response/fragments` | `APPEND` | array | new fragment appended (type switch) |
| `response/status` | `SET` | string | status change (FINISHED, etc.) |
| `accumulated_token_usage` | `SET` | number | token usage |
| `response` | `BATCH` | array | batch update (multiple `{p,v}` pairs) |

#### type C: response metadata
```json
{"v": {"response": {"message_id": 4, "parent_id": 3, "fragments": [...], "thinking_enabled": true, ...}}}
```
- Appears early in the SSE stream (the first data event).
- Contains full response metadata: message_id, parent_id, fragments, status, etc.
- The `fragments` array contains the initial fragment info.
- `status: "WIP"` means generating, `"FINISHED"` means done.

#### type D: ready event (event: ready)
```
event: ready
data: {"request_message_id": 1, "response_message_id": 2, "model_type": "expert"}
```
- Appears only after an `event: ready` line.
- Tells you the request/response message_id mapping.
- `model_type` indicates the actual model type used (`"default"` or `"expert"`).

### 6.3 Quick-mode SSE event sequence

```
event: ready
data: {"request_message_id":1,"response_message_id":2,"model_type":"default"}

event: update_session
data: {"updated_at": ...}

data: {"v": {"response": {"message_id":2, "status":"WIP", "content":"", ...}}}

data: {"p":"response/content","o":"APPEND","v":"Hello"}
data: {"v":" World"}
data: {"v":"!"}
data: {"p":"response/status","o":"SET","v":"FINISHED"}

event: update_session
data: {"updated_at": ...}

event: close
data: {"click_behavior":"none","auto_resume":false}
```

### 6.4 Expert-mode SSE event sequence

Expert mode uses the **Fragment system**; the response content is composed of multiple fragments (THINK → RESPONSE).

```
event: ready
data: {"request_message_id":1,"response_message_id":2,"model_type":"expert"}

event: update_session
data: {"updated_at": ...}

// initialize the response, with fragments[0] = THINK
data: {"v":{"response":{"message_id":2, "fragments":[{"id":2,"type":"THINK","content":"initial reasoning"}], "thinking_enabled":true, ...}}}

// thinking-phase tokens (belong to the current THINK fragment)
data: {"v":"reasoning"}
data: {"p":"response/fragments/-1/content","o":"APPEND","v":" process"}
data: {"v":" continues"}

// fragment switch: append the RESPONSE fragment
data: {"p":"response/fragments","o":"APPEND","v":[{"id":3,"type":"RESPONSE","content":"","references":[],"stage_id":1}]}
data: {"p":"response/fragments/-1/elapsed_secs","o":"SET","v":7.21}

// answer-phase tokens (belong to the RESPONSE fragment)
data: {"p":"response/fragments/-1/content","v":"final"}
data: {"v":" answer"}
data: {"v":" content"}

// batch update (token usage + status)
data: {"p":"response","o":"BATCH","v":[{"p":"accumulated_token_usage","v":457},{"p":"quasi_status","v":"FINISHED"}]}

// final status
data: {"p":"response/status","o":"SET","v":"FINISHED"}

event: update_session
data: {"updated_at": ...}

event: close
data: {"click_behavior":"none","auto_resume":false}
```

### 6.5 Fragment types

| Type | Meaning | Contents |
|------|------|---------|
| `THINK` | Reasoning/thinking process | The model's internal reasoning chain, visible to the user |
| `RESPONSE` | Final answer | The formal user-facing reply |
| `TEXT` | Text fragment | Generic text (rare) |

### 6.5 SSE event-type reference

#### `event: ready`

The first event in the SSE stream, carrying the request/response message_id mapping:

```
event: ready
data: {"request_message_id": 1, "response_message_id": 2, "model_type": "expert"}
```

- `request_message_id` — the request ID assigned by the DeepSeek server.
- `response_message_id` — the response ID assigned by the DeepSeek server (the `message_id` in the later `{"v": {"response": {...}}}` matches this).
- `model_type` — the actual model type used (`"default"` or `"expert"`), matching the request body's `model_type`.

#### `event: update_session`

Session-update event, appearing between key points (response start, response end):

```
event: update_session
data: {"updated_at": 1778077771}
```

- Usually appears twice: once after ready, once before close.
- `updated_at` is the server's session update timestamp.
- The current implementation **ignores this event** and does nothing.

#### `event: close`

SSE stream end event:

```
event: close
data: {"click_behavior": "none", "auto_resume": false}
```

- `click_behavior` — the web app's click behavior ("none" or "resume").
- `auto_resume` — whether to auto-resume.
- The current implementation **ignores this event** and does nothing.
- There should be no more data lines after the stream closes.

#### The `BATCH` operation type

When the operation value is `"BATCH"`, `v` is an array containing multiple `{p, v}` pairs:

```json
{"p": "response", "o": "BATCH", "v": [
  {"p": "accumulated_token_usage", "v": 457},
  {"p": "quasi_status", "v": "FINISHED"}
]}
```

Common `p` values inside BATCH:

| Path | v type | Meaning |
|------|--------|------|
| `accumulated_token_usage` | number | cumulative token usage |
| `quasi_status` | string | quasi-status ("FINISHED", etc.) |
| `response/fragments/-1/elapsed_secs` | number | current fragment elapsed time |
| `response/status` | string | status ("WIP", "FINISHED") |
| `response/content` | string | full or incremental content |

BATCH usually appears in quick mode and is used less in expert mode. The current implementation does **no special handling** of BATCH events (there is no matching parse branch), but the non-streaming mode captures all events via `_parse_sse()`.

#### `accumulated_token_usage`

Appears in a BATCH or a standalone SET event, representing the total tokens consumed so far (note: not the full count for this response, but a cumulative value). Currently not returned to the client as `usage` (`server.py`'s `usage` field is hardcoded to `-1`).

#### `quasi_status`

A status field used internally by DeepSeek, synced with `response/status`. A value of `"FINISHED"` means the response ended. The current implementation does not handle this field and relies on the `response/status SET` event.

### 6.6 Non-streaming SSE parser `_parse_sse()`

`adapter.py`'s `_parse_sse()` is used in non-streaming mode and differs from `chat_stream()`'s streaming parser in a few ways:

| Feature | `_parse_sse()` (non-streaming) | `chat_stream()` (streaming) |
|------|------------------------|----------------------|
| Input | Full response text (str) | `resp.iter_lines()` generator |
| Parse timing | Parses all events at once | Processes line by line in real time |
| event tracking | Tracks `current_event` but unused | Tracks `current_event` but unused |
| JSON-failure handling | Stores the raw string | Skips the line |
| Output | `list[(event_type, data)]` | `yield str/dict` |
| Fragment state machine | Implemented in `chat()` (iterating the event list) | Inline in the parse loop |

`_parse_sse()` is a **generic parser** that does not care about specific business logic. The fragment state machine and other business logic are implemented in the caller (`chat()`). This is an architectural difference from streaming mode — streaming embeds the state machine directly in the parse loop.

---

## 7. MODE / THINKING / SEARCH Control System

### 7.1 Design idea

DeepSeek's API has three independent parameters controlling model behavior:
- **`model_type`**: `"default"` (quick mode) or `"expert"` (expert mode)
- **`thinking_enabled`**: `true/false` — whether to output the reasoning process
- **`search_enabled`**: `true/false` — whether to enable web search

**Key insight: these three parameters are fully independent.**

Older versions mistakenly equated `thinking_enabled=true` with expert mode. In reality `model_type="default"` (quick mode) + `thinking_enabled=true` is also a valid combination — quick mode can also enable thinking. Likewise `search_enabled` is fully independent of `model_type` and `thinking_enabled`.

The project exposes these three degrees of freedom via three `.env` environment variables:

| Env var | Controlled parameter | Values |
|---------|---------|-------|
| `MODE` | `model_type` | `auto` / `quick` / `expert` |
| `THINKING` | `thinking_enabled` | `auto` / `enabled` / `disabled` |
| `SEARCH` | `search_enabled` | `auto` / `enabled` / `disabled` |

`auto` means "decided by the corresponding field in the client request"; a non-`auto` value overrides the client's parameter.

### 7.2 Implementation (`server.py`)

```python
# server.py module level
MODE = os.environ.get("MODE", "auto").strip().lower()
THINKING = os.environ.get("THINKING", "auto").strip().lower()
SEARCH = os.environ.get("SEARCH", "auto").strip().lower()

# in chat_completions()
if MODE == "expert":
    model_type = "expert"
else:  # "quick" or "auto"
    model_type = "default"

if THINKING == "enabled":
    thinking = True
elif THINKING == "disabled":
    thinking = False
else:  # "auto"
    thinking = req.thinking_mode or False

if SEARCH == "enabled":
    search = True
elif SEARCH == "disabled":
    search = False
else:  # "auto"
    search = req.search_enabled or False
```

Note that `model_type` is set to `"default"` (not `None`) when `MODE` is not `expert`. This matches DeepSeek's native request format.

### 7.3 Eight combinations and OpenAI SSE behavior

| MODE | THINKING | SEARCH | model_type | thinking_enabled | search_enabled | Actual effect |
|------|----------|--------|------------|-----------------|---------------|---------|
| quick | disabled | auto | `"default"` | `false` | from client | quick mode, no thinking |
| quick | enabled | disabled | `"default"` | `true` | `false` | quick mode + thinking, search off |
| quick | enabled | enabled | `"default"` | `true` | `true` | quick + thinking + search |
| expert | disabled | auto | `"expert"` | `false` | from client | expert mode, no thinking |
| expert | enabled | auto | `"expert"` | `true` | from client | full expert mode |
| expert | enabled | enabled | `"expert"` | `true` | `true` | expert + thinking + search |
| auto | auto | auto | `"default"` | `req.thinking_mode` | `req.search_enabled` | fully client-decided |
| quick | auto | enabled | `"default"` | `req.thinking_mode` | `true` | quick mode + forced search |

All combinations have been verified against raw SSE captures.

**Fallback behavior when MODE=auto:**
- MODE=auto → model_type="default" (quick mode)
- THINKING=auto → thinking = req.thinking_mode or False
- SEARCH=auto → search = req.search_enabled or False

### 7.4 SEARCH env var in detail

`SEARCH` controls the `search_enabled` parameter, deciding whether the model can search the web for real-time information.

| Value | Effect | search_enabled |
|----|------|---------------|
| `auto` | decided by the request's `search_enabled` | `req.search_enabled or False` |
| `enabled` | force web search on | `True` |
| `disabled` | force web search off | `False` |

**Notes:**
- `search_enabled` only tells the model "you may search the web"; the model decides for itself whether it needs to search.
- Search results appear in the reply as `[citation:N]` reference markers, which are stripped automatically by `_clean_dsml_text()`.
- This parameter is fully independent of `model_type` and `thinking_enabled`; all 2×2×2=8 combinations are valid.

### 7.5 SSE format for "quick mode + thinking"

Quick mode also uses the Fragment system (no `model_type: "expert"` needed), so its SSE format is identical to expert mode:

```
// initial response with fragments[0] = THINK
data: {"v":{"response":{"fragments":[{"type":"THINK","content":"reasoning..."}],...}}}

// thinking tokens
data: {"v":"reasoning"}
data: {"p":"response/fragments/-1/content","o":"APPEND","v":"in progress"}

// switch to RESPONSE
data: {"p":"response/fragments","o":"APPEND","v":[{"type":"RESPONSE",...}]}

// content tokens
data: {"v":"final"}

// end
data: {"p":"response/status","o":"SET","v":"FINISHED"}
```

### 7.6 Expert Mode core differences

When `model_type="expert"`, beyond MODE control there are these extra differences:

| Dimension | Quick mode | Expert mode |
|------|---------|---------|
| `model_type` | `"default"` | `"expert"` |
| SSE content format | same as above (both may use fragments) | same as above (both may use fragments) |
| Fragment system | optional (model decides) | always has THINK → RESPONSE |
| `reasoning_content` | depends on THINKING | depends on THINKING |
| Request-header requirements | lenient | needs `X-Client-Version: 2.3.0` etc. (see 7.7) |

In practice DeepSeek's quick and expert modes differ very little at the SSE protocol level; `model_type` mainly affects which model is chosen and its reasoning depth.

### 7.7 Request-header requirements (as of 2026-08)

Current request headers confirmed from a HAR capture (2026-08-02, browser Chrome 150):

```
X-Client-Version: 2.3.0          ← current browser version (the old 2.0.0 era is over)
X-Client-Platform: web
X-Client-Locale: zh_CN
X-Client-Timezone-Offset: 28800
x-client-bundle-id: com.deepseek.chat
X-Hif-Leim / X-Hif-Dliq          ← signature headers (since v3.2.2 the adapter auto-sends them via _HifProvider, see 7.13)
```

**`X-App-Version` is deprecated**: as of 2026-08 the real browser no longer sends this header (the old `20241129.1`/`2.0.0` era is over). The adapter removed this header in v3.2.0.

> History: in the v2.x era `X-App-Version: 0.0.1` made the server return `"Update to the latest version to use Expert."` (a toast event, parsed and surfaced since v3.2.0). The upstream's current "version too old" judgment is based mainly on `X-Client-Version`.

Other headers the browser sends automatically (`sec-ch-ua`, `sec-fetch-*`) are not strictly validated (but TLS/JA3 fingerprints are apparently detected — automation fingerprints (curl_cffi/tls-client) get rate-limited by the upstream at high frequency, see the v3.2.1 summary).

### 7.8 State machine (`frag_type` in `chat_stream`)

```python
frag_type = None  # state: None | 'thinking' | 'content'
```

State transitions:

```
[initial] None
  │
  ├─ response has fragments[0].type == "THINK" → frag_type = "thinking"
  │    │
  │    ├─ receive "response/fragments APPEND" with type="RESPONSE" → frag_type = "content"
  │    │    │
  │    │    └─ subsequent tokens emitted as content
  │    │
  │    └─ meanwhile all tokens emitted as __type="thinking"
  │
  └─ response has empty fragments or no THINK → frag_type = "content"
```

The state machine runs in both modes — whether `model_type="default"` (quick) or `model_type="expert"` (expert), DeepSeek may return a THINK fragment. The difference is that in expert mode a THINK fragment almost always appears, whereas in quick mode the model decides for itself.

### 7.9 The SSE `reasoning_content` field

In OpenAI's Stream Options, `reasoning_content` is a non-standard field used by several vendors (DeepSeek's official API, OpenAI o1, etc.). In streaming output this project:

1. **Emits `{"reasoning_content": ""}` on the first thinking token** (an empty frame marking the start of thinking).
2. Emits `{"reasoning_content": "..."}` for each subsequent thinking token.
3. Resumes `{"content": "..."}` after switching to the content phase.
4. **Emits `{"finish_reason": "stop"}` at the end of the stream** (§7.10).

**The empty `reasoning_content: ""` trap:**

The initial version emitted the empty frame unconditionally before the first content. When THINKING=disabled, some clients (e.g. Claude Code) interpreted this empty frame as "the response has only empty reasoning", producing `parts: []`, `finish: "other"` — the entire reply disappeared.

**Fix (2026-05-06):** in streaming, `reasoning_content: ""` is emitted only when:
1. Processing a thinking token (`adapter` yields an `__type:"thinking"` dict) → emitted unconditionally (already in the thinking flow, reasonable).
2. Processing a content token with `role_sent=False` → **emitted only when `thinking_mode=True`**.

```python
# server.py _handle_stream event_stream()

# Thinking path: emit the empty frame unconditionally (already inside the thinking block)
if not role_sent:
    yield _openai_chunk(proxy_id, reasoning_content="")
    role_sent = True
yield _openai_chunk(proxy_id, reasoning_content=content)

# Text path: emit the empty frame only when thinking_mode=True
if not role_sent:
    if thinking_mode:
        yield _openai_chunk(proxy_id, reasoning_content="")
    role_sent = True
yield _openai_chunk(proxy_id, content=evt.data)
```

### 7.10 The `finish_reason: "stop"` end frame

**Problem:** the streaming response lacked a `finish_reason` end frame. The standard OpenAI SSE format requires an empty delta + `finish_reason` before `[DONE]`:

```json
data: {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}

data: [DONE]
```

The original code only sent `finish_reason: "tool_calls"` from `_emit_tool_calls_chunks` on the tool_calls path, while the normal end path sent `[DONE]` directly, missing `finish_reason: "stop"`.

**Impact:** some clients mark a stream lacking `finish_reason` as `finish: "other"`, possibly causing abnormal response handling (e.g. only the reasoning part is kept, content is not displayed).

**Fix (2026-05-07):** add on the normal end path:

```python
yield _openai_chunk(proxy_id, finish=True)
yield "data: [DONE]\n\n"
```

`_openai_chunk(proxy_id, finish=True)` yields:
```json
{"delta": {}, "finish_reason": "stop"}
```

**Affected locations:** 1 (the normal end path). The tool_calls paths (3 of them) already have `finish_reason: "tool_calls"` and need no change.

### 7.11 Non-streaming mode limitation

In non-streaming mode `adapter.chat()` returns only the **RESPONSE content** from `response/content` or `response/fragments/-1/content`. THINK content is not included in the return value. This is because in non-streaming mode:

- If `response/content APPEND` is used, the content already includes the final reply.
- If the fragments approach is used, `chat()` collects only the RESPONSE fragment's content.

To return both thinking and content in non-streaming mode, the `chat()` method would need to be modified to support a structured return.

### 7.12 Request-body fields in detail

The full request body contains the following fields (`adapter.py:171-181`):

```json
{
  "chat_session_id": "<session-uuid>",
  "parent_message_id": null,
  "model_type": "default",
  "prompt": "User: Hello",
  "ref_file_ids": [],
  "stream": true,
  "thinking_enabled": false,
  "search_enabled": false,
  "preempt": false
}
```

| Field | Type | Quick mode | Expert mode | Notes |
|------|------|---------|---------|------|
| `chat_session_id` | string | required | required | session ID returned by `create_session()` |
| `parent_message_id` | int/null | null | null | ID of the previous message, null for the first |
| `model_type` | string | `"default"` | `"expert"` | **key switch**, decided by the MODE env var |
| `prompt` | string | required | required | concatenated plain-text prompt |
| `ref_file_ids` | list | `[]` | `[]` | file-reference IDs, always empty (no file upload) |
| `stream` | bool | as needed | as needed | server-side SSE streaming switch |
| `thinking_enabled` | bool | decided by THINKING | decided by THINKING | enable reasoning output |
| `search_enabled` | bool | decided by SEARCH | decided by SEARCH | enable web search |
| `preempt` | bool | false | false | preempt mode, always false |

**How `model_type`, `thinking_enabled`, `search_enabled` cooperate:**

| Scenario | model_type | thinking_enabled | search_enabled | Notes |
|------|-----------|-----------------|---------------|------|
| Pure quick mode | `"default"` | `false` | `false` | basic mode |
| Quick + thinking | `"default"` | `true` | `false` | fast response with reasoning attached |
| Quick + search | `"default"` | `false` | `true` | fast response + web search |
| Expert, no thinking | `"expert"` | `false` | `false` | expert model but no reasoning output (rare) |
| Full expert | `"expert"` | `true` | `true` | expert model + full reasoning + web search |

#### The `preempt` field

`preempt: false` means "do not preempt the response currently in progress". If set to `true`, it could in theory interrupt a reply being generated in the same session and start a new one. The current implementation always uses `false`. Setting it to `true` by mistake may cause undefined behavior.

#### The `ref_file_ids` field

The DeepSeek Chat web app supports uploading files (images, PDFs); after upload a file gets an ID, attached to the conversation via this field. The current adapter does not support file upload, so it always passes an empty array. To implement it you would need:
1. An extra endpoint: file upload → get a file_id.
2. Pass the file_id into `ref_file_ids`.
3. Clean up the server-side file association.

#### `search_enabled` behavior

`search_enabled: true` tells the DeepSeek model it may search the web when needed. After this parameter is passed through to the server:
- The server decides whether to search (the model judges for itself).
- Search results appear in the reply as `[citation:N]`.
- The current implementation strips `[citation:N]` markers in `_clean_dsml_text()`.
- Web-search mode is **not heavily tested** yet, so it is marked ⚠️.

#### `stream` field behavior

Note that `stream` means different things in `adapter.py` and `server.py`:
- **adapter layer**: `stream=True` returns an SSE stream from the server; `stream=False` returns the full response body at once.
- **server layer**: streaming is decided by `server.py`'s routing choosing `_handle_stream` vs `_handle_nonstream`, but internally it always calls `adapter.chat_stream()` (streaming) or `adapter.chat()` (non-streaming) — there is no "streaming server implemented with a non-streaming adapter" path.

### 7.13 Pass-through parameter panorama: client → server → upstream DeepSeek

> This section answers one question: **in what form and with what value does each client field finally hit `chat.deepseek.com` upstream.** All info corresponds to the actual `adapter.py` code (request-body construction, `_base_headers`).

#### The three upstream endpoints (BASE_URL = `https://chat.deepseek.com`)

| Endpoint | Purpose | Request body |
|------|------|--------|
| `POST /api/v0/chat/create_pow_challenge` | get the PoW challenge | `{"target_path": "/api/v0/chat/completion"}` |
| `POST /api/v0/chat_session/create` | create a session | `{"target_path": "/api/v0/chat/completion"}` |
| `POST /api/v0/chat/completion` | conversation (shared by streaming/non-streaming) | see below |

#### `/api/v0/chat/completion` request body (what the adapter actually sends, field by field)

| Field | Value source | Notes |
|------|--------|------|
| `chat_session_id` | returned by `create_session()` | session UUID |
| `parent_message_id` | adapter `_msg_counters` or the server session cache | `null` for the first; across turns, returned by the server's `SESSION_CACHE_TTL` cache |
| `model_type` | server decision (MODEL_ROUTES/MODE) | `"default"` (quick) \| `"expert"` (expert), **key switch** |
| `prompt` | server `_build_prompt()` | client messages concatenated into plain text |
| `ref_file_ids` | fixed `[]` | no file upload |
| `stream` | server-layer `req.stream` | `true`=SSE streaming / `false`=return at once |
| `thinking_enabled` | server decision (THINKING/client) | reasoning switch, **independent of `model_type`** |
| `search_enabled` | server decision (SEARCH/client) | web-search switch |
| `preempt` | fixed `false` | preempt mode; do not set `true` (undefined behavior) |

#### Request headers (`_base_headers`, mimicking a real browser)

| Header | Value |
|----|----|
| `User-Agent` / `Sec-Ch-Ua` / `Sec-Ch-Ua-Mobile` / `Sec-Ch-Ua-Platform` | Chrome fingerprint (`DEEPSEEK_IMPERSONATE` ties into the curl_cffi fingerprint) |
| `Accept` / `Accept-Encoding` / `Accept-Language` | browser style (`gzip, deflate, br, zstd` / `zh-CN,...`) |
| `Content-Type` | `application/json` |
| `Authorization` | `Bearer <DeepSeek token>` (account credential) |
| `Origin` / `Referer` | `https://chat.deepseek.com/` |
| `Priority` | `u=1, i` |
| `Sec-Fetch-Dest` / `Sec-Fetch-Mode` / `Sec-Fetch-Site` | `empty` / `cors` / `same-origin` |
| `X-App-Version` / `X-Client-Version` | `2.0.0` (too low is rejected for expert mode by the upstream) |
| `X-Client-Platform` / `X-Client-Locale` / `X-Client-Timezone-Offset` | `web` / `zh_CN` / `28800` |
| `x-client-bundle-id` | `com.deepseek.chat` |
| `X-DS-PoW-Response` | **dynamic**: solved before each request, `base64(json PoW token)` |

#### Client parameter → upstream field mapping chain

**OpenAI `/v1/chat/completions`:**

| Client field | Server decision (highest to lowest priority) | Upstream field |
|-----------|------------------------------|---------|
| `model` | `MODEL_ROUTES` hit → its model_type; else `MODE=expert` → `"expert"`; else `"default"` | `model_type` |
| `thinking_mode` | `MODEL_ROUTES.thinking` → `THINKING=enabled/disabled` → client `thinking_mode` | `thinking_enabled` |
| `search_enabled` | `MODEL_ROUTES.search` → `SEARCH=enabled/disabled` → client `search_enabled` | `search_enabled` |
| `stream` | direct | `stream` |
| `temperature` / `top_p` / `max_tokens` | **read then discarded**, not passed through | — |
| `tools` / `tool_choice` | server converts to DSML and injects into `prompt` (see chapter 8) | not a separate field |

**Anthropic `/v1/messages`:**

| Client field | Server decision | Upstream field |
|-----------|------------|---------|
| `model` | same as OpenAI | `model_type` |
| `thinking.type="enabled"` | mapped to `thinking_mode`, then the same chain | `thinking_enabled` |
| `metadata.user_id` | session-cache key (`SESSION_CACHE_TTL`) | `parent_message_id` (multi-turn) |
| `system` / `messages` | concatenated by `_build_prompt()` | `prompt` |
| `max_tokens` / `stop_sequences` / `temperature` | **ignored** | — |

#### Environment-variable priority summary (highest → lowest)

```
MODEL_ROUTES hit (by model name) → MODE / THINKING / SEARCH env → client fields (thinking_mode / search_enabled)
```

When `MODE`/`THINKING`/`SEARCH` are all `auto`, `model_type` is always `"default"` and thinking/search are client-decided; `MODEL_ROUTES` affects only matched model names, and unmatched models fall back to the env logic (see the 7.12 cooperation table).

---



## 8. Tool Calls (DSML)

### 8.1 Principle

DeepSeek Chat's API does not natively support tool calling (function calling). This project implements it via **DSML (DeepSeek Markup Language) prompt injection**.

The core idea: turn tool definitions into text instructions injected into the system message, have the model understand them and reply in an XML format, then parse that back into the OpenAI standard format.

### 8.2 Flow

```
Client sends the tools array
  │
  ▼
server.py: build_dsml_tool_prompt(tools)
  │  turn tool definitions into DSML-format text:
  │  "You have access to tools. When you need to call a tool,
  │   respond with EXACTLY this format — no markdown fences...
  │   Available tools:
  │     get_weather: get the weather for a given city
  │     search_web: search the web"
  │
  ▼ inject into the system message
_build_prompt() prepends the DSML instructions to the prompt
  │
  ▼
The DeepSeek model understands the instructions and may reply with DSML XML:
  ├─ normal reply ("Beijing is 25 degrees today")
  └─ tool call (<|DSML|tool_calls>...)
        │
        ▼
      streaming: StreamSieve detects DSML tags in real time
      non-streaming: parse_dsml_tool_calls() parses the whole thing
        │
        ▼
      convert to the OpenAI standard tool_calls format
```

### 8.3 DSML XML format

```xml
<|DSML|tool_calls>
  <|DSML|invoke name="get_weather">
    <|DSML|parameter name="city"><![CDATA[Beijing]]></|DSML|parameter>
  </|DSML|invoke>
</|DSML|tool_calls>
```

Notes:
- If a `parameter` value is a string, it must be wrapped in CDATA.
- Numbers, booleans, and null are written directly as text.
- Nested objects are not supported (use JSON.stringify and pass via CDATA).
- The `invoke` `name` attribute needs XML escaping (`&` → `&amp;`, etc.).

### 8.4 DSML parsing (`tool_dsml.py`)

**`strip_dsml_markup(text)`** — removes the `|DSML|` prefix, keeping the pure XML structure. Scans character by character, handling CDATA content and `|DSML|`-prefixed tags.

**`parse_dsml_tool_calls(text, tool_names)`** — extracts tool calls from text.

Parsing strategy:
1. Call `strip_dsml_markup()` to normalize the text.
2. Match `<tool_calls>...</tool_calls>` or `<tool_call>...</tool_call>` blocks.
3. When there is no outer wrapper, match the bare `<invoke>` directly.
4. Extract parameters from each `<parameter>` inside an invoke.
5. Try JSON.parse on parameter values; on failure, use `_auto_type` for smart conversion.

**`_auto_type(val)`** — smart type inference:

| Input | Output |
|------|------|
| `"true"` | `True` (bool) |
| `"false"` | `False` (bool) |
| `"null"`, `"none"` | `None` |
| `"42"` | `42` (int) |
| `"3.14"` | `3.14` (float) |
| `"hello"` | `"hello"` (str) |

**`format_tool_calls_for_prompt(tool_calls_raw)`** — converts OpenAI tool_calls back to DSML format, used when replaying history messages.

**`build_dsml_tool_prompt(tools)`** — generates the tool-instruction prompt.

### 8.5 Replaying tool-call history

In a multi-turn conversation, if a previous assistant reply contained tool calls, they must be converted back to DSML format and concatenated into the prompt on the next request:

```
Assistant: Let me check the weather. format_tool_calls_for_prompt(...)
Tool result: {"temperature": 25}
User: What about humidity?
```

`_build_prompt()` handles the `tool_calls` field of the `assistant` role, converting it to DSML via `format_tool_calls_for_prompt()` and appending it after the message text.

### 8.6 Known limitations

- **No parallel tool calls**: only one tool can be called at a time.
- **`tool_choice` unreliable**: the model may choose not to call a tool.
- **Format instability**: it depends on the model emitting exactly the DSML format; a missing tag or extra spaces can break parsing.
- **DSML parse-failure fallback**: if DSML parsing fails, the tool-call content is cleaned and returned as plain text.

### 8.7 DSML internal-function reference

#### `extract_cdata(text)` — CDATA extraction

```python
def extract_cdata(text: str) -> str:
    text = text.strip()
    if text.startswith("<![CDATA[") and text.endswith("]]>"):
        return text[len("<![CDATA["):-len("]]>")]
    return text
```

Extracts CDATA-wrapped content from a parameter value. If the text is not CDATA format, returns it unchanged.

#### `_auto_type(val)` — smart type inference

Converts a DSML parameter's string value to a native Python type. Conversion priority:

1. Boolean: `"true"` → `True`, `"false"` → `False`.
2. Null: `"null"`, `"none"` → `None`.
3. Integer: `"42"` → `42`.
4. Float: `"3.14"` → `3.14`.
5. String: otherwise returned unchanged.

**Note:** this function is called after CDATA extraction. If the parameter value was passed in as JSON (i.e. `json.loads` succeeds), the JSON result is preferred. `_auto_type` is only a fallback when JSON parsing fails.

#### `_clean_dsml_text(text)` — clean DSML markup

Removes all DSML-related markup from text, returning clean text. Performs the following cleanup:

| Step | Regex/operation | Cleanup target |
|------|----------|---------|
| 1 | `<tool_calls>...</tool_calls>` | tool-call outer wrapper |
| 2 | `<invoke ...>...</invoke>` | a single tool call |
| 3 | `<parameter ...>...</parameter>` | parameter declarations |
| 4 | `<![CDATA[...]]>` | CDATA markers |
| 5 | `[citation:N]` | DeepSeek web-search reference markers |
| 6 | 3+ consecutive newlines → 2 | blank-line compaction |

**`[citation:N]` reference markers:** when `search_enabled: true`, DeepSeek may insert reference markers like `[citation:1]` in the reply. These are meaningless to the user (no link to follow), so they are stripped uniformly.

#### `format_tool_calls_for_prompt()` — replaying tool-call history

Converts OpenAI-format tool_calls back to DSML format for multi-turn conversations. The input is compatible with the following formats:

```json
// Format A: OpenAI standard
{"id": "call_xxx", "type": "function", "function": {"name": "get_weather", "arguments": "{\"city\": \"Beijing\"}"}}

// Format B: simplified
{"name": "get_weather", "arguments": {"city": "Beijing"}}

// Format C: native
{"name": "get_weather", "input": "{\"city\": \"Beijing\"}"}
```

Output:
```xml
<|DSML|tool_calls>
  <|DSML|invoke name="get_weather">
    <|DSML|parameter name="city"><![CDATA[Beijing]]></|DSML|parameter>
  </|DSML|invoke>
</|DSML|tool_calls>
```

#### Parameter-formatting rules

`_format_params_dsml()` handles DSML serialization of different Python types:

| Python type | DSML output | Example |
|------------|----------|------|
| `None` | empty tag | `<parameter name="x"></parameter>` |
| `str` | CDATA-wrapped | `<parameter name="x"><![CDATA[hello]]></parameter>` |
| `int/float/bool` | plain text | `<parameter name="x">42</parameter>` |
| `dict/list` | CDATA-wrapped JSON | `<parameter name="x"><![CDATA[{"key":"value"}]]></parameter>` |

**Fix (2026-05-07):** historically dict/list parameters were serialized to an empty tag (`<parameter name="x"></parameter>`), losing nested parameters. The fix uses `json.dumps()` to serialize to a JSON string, then wraps it in CDATA, preserving the full nested structure.

---



## 9. StreamSieve Streaming Sieve Engine

### 9.1 Problem it solves

In streaming mode, DeepSeek returns text token by token. When a tool call happens, DSML XML tags and plain-text tokens are interleaved. StreamSieve must detect and separate text from tool-call tags in real time at the token level.

### 9.2 Dual-buffer design

```
Pending buffer (_pending)
  │ stores text not yet judged to be a tool call
  │ avoids truncating a token at a tag boundary
  ▼
A DSML start marker is detected
  │ (e.g. <|DSML|tool_calls>, <invoke, <tool_calls>)
  ▼
Capture buffer (_capture_buf)
  │ captures all subsequent tokens from the marker
  │ continues until a closing tag is detected
  ▼
Capture done → parse_fn parses → a SieveEvent is emitted
  │ type='tool_calls' or type='text'
  ▼
Buffers and state are reset
```

### 9.3 Core methods

**`feed(chunk)`** — process a new token:

```
flow:
1. If currently in the _capturing state:
   a. append chunk to _capture_buf
   b. try _try_finish_capture()
   c. if done, emit the event and reset; otherwise keep waiting

2. If not in the _capturing state:
   a. append chunk to _pending
   b. search _pending with _find_tool_start()
   c. marker found:
      - text before the marker is emitted as a text event
      - the remainder moves into _capture_buf
      - try _try_finish_capture()
   d. marker not found:
      - _split_safe() emits the safe part, possibly keeping a trailing tail that could start a marker
```

**`flush()`** — handle residual buffers at the end of the stream:
- an unclosed tool call in `_capture_buf` → emitted as plain text
- residual text in `_pending` → emitted

**`_find_tool_start(text)`** — search for a DSML start marker in text:

```python
_TOOL_STARTS = [
    "<|DSML|tool_calls>",
    "|DSML|tool_calls>",
    "<tool_calls>",
    "<tool_call>",
    "<invoke ",
    "<|DSML|invoke ",
    "|DSML|invoke ",
]
```

It also detects prefixes: `<|DSML|`, `|DSML|`, `<tool_calls`, `<tool_call`, `<invoke`.

**`_split_safe(text)`** — split text, avoiding truncation at a possible marker start:

Within a window of the longest tag length from the end of the text, find the **earliest** `<` or `|`; as long as the tail from that position could still be a prefix of any `_TOOL_STARTS` / `_TOOL_PREFIXES`, keep that tail in `_pending` and emit the rest as safe text. (Previously only the last `<` or `|` was considered: when a tag is streamed token by token, the last special char in `<|` is `|`, so `<` was emitted as body text, and the client saw an extra `<` before each streaming tool call.)

**`_is_capture_complete()`** — decide whether the capture is complete:

- if `_capture_buf` contains `<|DSML|tool_calls>` or `<tool_calls>` → wait for the matching closing tag
- if it contains `<invoke` or `<|DSML|invoke` → wait for `</invoke>` or `</|DSML|invoke>`

### 9.4 Event model

```python
@dataclass
class SieveEvent:
    type: str      # 'text' | 'tool_calls'
    data: Any      # str (for text) | list[dict] (for tool_calls)
```

### 9.5 Streaming fallback mechanism

`_handle_stream` in server.py has two layers of protection:

1. **Main path**: StreamSieve sieves in real time; on detecting a tool call it emits a tool_calls event immediately and ends the stream.
2. **Flush path**: at the end of the stream, `sieve.flush()` handles residue.
3. **Fallback path**: if the sieve misses detection (rare), re-run `parse_dsml_tool_calls()` over `full_buf` (the full buffer) to parse the whole thing.

```python
if not had_tool and full_buf:
    tc_result, _ = parse_dsml_tool_calls(full_buf, tool_names)
    if tc_result:
        # emit a tool-call event
        ...
```

---

## 10. OpenAI Compatibility Layer

### 10.1 Endpoints

| Endpoint | Method | Function | server.py handler |
|------|------|------|-------------------|
| `/health` | GET | health check | `health()` |
| `/v1/models` | GET | model list | `list_models()` |
| `/v1/chat/completions` | POST | chat completion | `chat_completions()` |

### 10.2 Request model (`ChatCompletionRequest`)

```python
class ChatCompletionRequest(BaseModel):
    model: Optional[str] = MODEL_NAME        # model name, customizable (does not affect forwarding)
    messages: list[ChatMessage]               # message list
    stream: Optional[bool] = False            # whether to stream
    max_tokens: Optional[int] = None          # currently ignored (pass-through ineffective)
    temperature: Optional[float] = None       # currently ignored
    top_p: Optional[float] = None             # currently ignored
    tools: Optional[list[ToolDef]] = None     # tool definitions
    tool_choice: Optional[Union[str, dict]] = None  # tool selection (unreliable)
    thinking_mode: Optional[bool] = False     # client-requested thinking mode (overridden by MODE/THINKING env)
    search_enabled: Optional[bool] = False    # web search
```

**Relationship between `thinking_mode` and the MODE/THINKING env vars:**

```
thinking_mode takes effect only when MODE=auto and THINKING=auto
  ↑
client request    → MODE=auto, THINKING=auto → thinking = req.thinking_mode
                 → MODE=expert               → model_type = "expert" (client ignored)
                 → THINKING=enabled          → thinking = True (client ignored)
```

That is: environment variables take priority over client parameters.

### 10.3 Streaming SSE format

```json
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1234567890,"model":"deepseek-chat","choices":[{"index":0,"delta":{},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1234567890,"model":"deepseek-chat","choices":[{"index":0,"delta":{"role":"assistant","content":null},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1234567890,"model":"deepseek-chat","choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1234567890,"model":"deepseek-chat","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

**The `finish_reason: "stop"` end frame must be included.** Standard OpenAI-compatible clients rely on it to judge whether the stream ended normally. Without it a client may report `finish: "other"` or `finish: null`, causing abnormal response handling.

**SSE sequence when thinking is on (`thinking_mode=true`):**

```json
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":...,"model":"deepseek-chat","choices":[{"index":0,"delta":{},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":...,"model":"deepseek-chat","choices":[{"index":0,"delta":{"reasoning_content":""},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":...,"model":"deepseek-chat","choices":[{"index":0,"delta":{"reasoning_content":"reasoning..."},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":...,"model":"deepseek-chat","choices":[{"index":0,"delta":{"content":"final answer"},"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":...,"model":"deepseek-chat","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

### 10.4 Tool-call SSE format (`_emit_tool_calls_chunks`)

```
frame 1: delta.tool_calls[0] = {id: "call_xxx", type: "function", function: {name: "get_weather", arguments: ""}}
frame 2: delta.tool_calls[0] = {function: {arguments: '{"city": "Beijing"}'}}
end frame: finish_reason = "tool_calls"
data: [DONE]
```

### 10.5 Non-streaming response format

```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "deepseek-chat",
  "choices": [{
    "index": 0,
    "message": {
      "role": "assistant",
      "content": "reply content"
    },
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": -1,
    "completion_tokens": -1,
    "total_tokens": -1
  }
}
```

With a tool call:
```json
"message": {
  "role": "assistant",
  "content": null,
  "tool_calls": [{
    "id": "call_xxx",
    "type": "function",
    "function": {"name": "get_weather", "arguments": "{\"city\": \"Beijing\"}"}
  }]
},
"finish_reason": "tool_calls"
```

### 10.6 Model-name handling

`MODEL_NAME` is configured via `.env`, default `"deepseek-chat"`. It can be set to any value such as `"gpt-4"` or `"deepseek-reasoner"`, which **does not affect actual forwarding** and is only used for the model field in the response.

---

## 11. Anthropic Compatibility Layer

### 11.1 Overview

The project adds support for the Anthropic Claude API format via the `POST /v1/messages` endpoint.

**Design principle:** the adapter layer is unchanged. Format conversion is done in a separate module, `anthropic_format.py`, isolated from the OpenAI logic.

### 11.2 Endpoint

| Endpoint | Method | Function |
|------|------|------|
| `/v1/messages` | POST | Anthropic-format chat completion |

### 11.3 Request mapping

| Anthropic field | Mapping |
|---------------|---------|
| `messages[].content` | extract text → concatenate into the prompt via `build_anthropic_prompt()` |
| `system` | prepended to the prompt as a System prefix |
| `thinking.type` | mapped to `thinking_mode`, overridden by the THINKING env |
| `tools` | converted to a DSML tool prompt and injected (reuses `build_dsml_tool_prompt()`) |
| `max_tokens` | ignored (DeepSeek does not support it) |
| `metadata` | ignored |
| `stop_sequences` | ignored |
| `stream` | controls the streaming/non-streaming path |

### 11.4 Streaming SSE format

Anthropic uses its own event types:

```
event: message_start
data: {"type":"message_start","message":{"id":"msg_...","type":"message","role":"assistant","content":[],...}}

event: content_block_start
data: {"type":"content_block_start","index":0,"content_block":{"type":"thinking","thinking":""}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"reasoning..."}}

event: content_block_stop
data: {"type":"content_block_stop","index":0}

event: content_block_start
data: {"type":"content_block_start","index":1,"content_block":{"type":"text","text":""}}

event: content_block_delta
data: {"type":"content_block_delta","index":1,"delta":{"type":"text_delta","text":"final answer"}}

event: content_block_stop
data: {"type":"content_block_stop","index":1}

event: message_delta
data: {"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null},...}

event: message_stop
data: {"type":"message_stop"}
```

With a tool call:
```
content_block_start(index, type="tool_use", id="toolu_...", name="get_weather", input={})
content_block_delta(index, type="input_json_delta", partial_json="...")
content_block_stop(index)
message_delta → stop_reason: "tool_use"
```

### 11.5 Non-streaming response

The Anthropic format uses a `content` array instead of OpenAI's single `content` string:

```json
{
  "id": "msg_...",
  "type": "message",
  "role": "assistant",
  "content": [
    {"type": "text", "text": "answer content"}
  ],
  "model": "deepseek-chat",
  "stop_reason": "end_turn",
  "stop_sequence": null,
  "usage": {"input_tokens": -1, "output_tokens": -1}
}
```

With a tool call:
```json
"content": [
  {"type": "tool_use", "id": "toolu_xxx", "name": "get_weather", "input": {"city": "Beijing"}}
],
"stop_reason": "tool_use"
```

With thinking (streaming only; non-streaming adapter.chat() does not return thinking):
```json
"content": [
  {"type": "thinking", "thinking": "reasoning..."},
  {"type": "text", "text": "answer content"}
]
```

### 11.6 Tool-call mapping

Anthropic uses `tool_use`/`tool_result` content-block types, corresponding to OpenAI's `tool_calls`/`tool` role:

| OpenAI | Anthropic |
|--------|-----------|
| `tool_calls[].function.name` | `tool_use.name` |
| `tool_calls[].function.arguments` (JSON string) | `tool_use.input` (parsed object) |
| `tool_calls[].id` | `tool_use.id` (prefix: `toolu_`) |
| `role: "tool"` + `tool_call_id` | `role: "user"` + `tool_result` block |

`build_anthropic_prompt()` converts `tool_use` blocks in multi-turn conversations to DSML format and `tool_result` blocks to a `Tool result:` prefix.

### 11.7 Key implementation

Core functions of `anthropic_format.py`:

| Function | Responsibility |
|------|------|
| `build_anthropic_prompt()` | Anthropic messages → internal prompt text |
| `build_nonstream_response()` | token stream → Anthropic non-streaming JSON |
| `stream_response()` | token stream → Anthropic SSE event generator |
| `_dsml_toolcalls_to_anthropic()` | OpenAI tool_calls → Anthropic tool_use blocks |
| `_emit_tool_use_blocks()` | tool_use → SSE content_block_start/delta/stop events |

### 11.8 MODE/THINKING/SEARCH interaction

Shares the MODE/THINKING/SEARCH env vars with the OpenAI endpoint:

```
THINKING=enabled  → force thinking=true (ignores the thinking param in the request)
THINKING=disabled → force thinking=false
THINKING=auto     → thinking = (request's thinking.type == "enabled")
```

---

## 12. Multi-turn Conversations and Message Assembly

### 11.1 `_build_prompt()`

Converts the OpenAI messages array into DeepSeek's plain-text format:

```
System: You are a helpful assistant.\n\ntool instructions...
User: What's the weather in Beijing?
Assistant: Let me check. <|DSML|tool_calls>...
Tool result: {"temperature": 25}
User: What about humidity?
```

### 11.2 Role mapping

| OpenAI role | Prompt prefix | Handling |
|-------------|------------|---------|
| `system` | `System: ` | concatenated directly; if tools present, append DSML instructions |
| `user` | `User: ` | extract content text |
| `assistant` | `Assistant: ` | text + tool_calls (converted to DSML) |
| `tool` | `Tool result: ` | truncated to the first 1000 chars |

### 11.3 Tool injection into the system message

When the request includes `tools`, the instructions generated by `build_dsml_tool_prompt()` are **injected at the end of the system message**. If there are multiple system messages, the instructions are concatenated into the first one. If there is no system message, a new system prefix is created.

---

## 13. ContentPart Support

### 12.1 Problem it solves

OpenAI's `content` field supports two formats:

```json
// Format A: plain string
{"role": "user", "content": "Hello"}

// Format B: ContentPart array
{"role": "user", "content": [{"type": "text", "text": "Hello"}]}
```

`_extract_text()` handles both uniformly:

```python
def _extract_text(content) -> str:
    if content is None:    return ""
    if isinstance(content, str):  return content
    # list[ContentPart] format
    return " ".join(p.text for p in content if p.type == "text" and p.text)
```

`type: "text"` ContentParts become the prompt. `type: "image_url"` parts (data URIs or http(s) URLs) ARE supported: the server resolves the bytes, the acquired account's adapter uploads them to DeepSeek (`upload_file` → poll `fetch_files` → `ref_file_ids`), and the completion runs as `model_type="vision"` (see §7.12). The Anthropic endpoint handles `image` content blocks the same way. Non-image file types (PDFs, etc.) are not wired.

### 12.2 Pydantic model

```python
class ContentPart(BaseModel):
    type: str
    text: Optional[str] = None
```

---

## 14. Configuration System

### 13.1 Environment variables

| Variable | Default | Notes |
|------|--------|------|
| `MODEL_NAME` | `deepseek-chat` | model name in responses (does not affect forwarding) |
| `PORT` | `8080` | server listen port |
| `MODE` | `auto` | mode control: `auto`/`quick`/`expert` |
| `THINKING` | `auto` | thinking control: `auto`/`enabled`/`disabled` |
| `SEARCH` | `auto` | web-search control: `auto`/`enabled`/`disabled` |
| `DEEPSEEK_JITTER_SECS` | `0.4` (v3.2.2+) | random sleep (0~N s) before an upstream call, to reduce the chance of tripping rate limiting; `0` disables |
| `DEEPSEEK_RATE_LIMIT_RETRY_DELAYS` | `5,15` (v3.2.2+) | backoff-second list on upstream rate limit (`rate_limit_reached`), each entry retries once with a new session; empty disables retries |
| `DEEPSEEK_MAX_CONCURRENCY` | `2` (v3.2.4+) | global upstream concurrency cap (across accounts); extra requests queue; coding-agent parallel subtasks do not flood the upstream |

> Other optional variables are in the table below (`.env.example` has full comments; this is a quick reference for agents/automation):

| Variable | Default | Purpose | Non-interactive importance |
|------|--------|------|------|
| Client API key | — | created/revoked on the WebUI "Settings" page; hash stored in `data/api_keys.sqlite3` | ⭐required (public) |
| `ALLOW_UNAUTHENTICATED_API` | `false` | whether to allow unauthenticated /v1/* | local dev only |
| `HOST` | `127.0.0.1` | listen address; `0.0.0.0`+default password refuses to start | ⭐relevant behind a proxy |
| `PORT` | `8080` | listen port | |
| `MODEL_NAME` | `deepseek-chat` | /v1/models display name (does not affect the actual model) | |
| `MODEL_ROUTES` | `""` | JSON route table, switch quick/expert by the model field | ⭐multi-model routing |
| `MODE` / `THINKING` / `SEARCH` | `auto` | three independent behavior dimensions | ⭐forced mode |
| `ACCOUNT_STORE_PATH` | `data/accounts.json` | account-pool persistence file path | ⭐non-interactive pool |
| `DEEPSEEK_ENCRYPTION_KEY` | `""` | Fernet key, encrypts accounts.json (v2) | ⭐public security |
| `CLIENT_RPM_PER_KEY` | `60` | requests per minute per key (0=unlimited) | ⭐rate limiting |
| `CLIENT_RPM_PER_IP` | `120` | requests per minute per IP (0=unlimited) | ⭐rate limiting |
| `ENABLE_RATE_LIMIT` | `true` | master rate-limit switch | |
| `SESSION_CACHE_TTL` | `1800` | multi-turn session cache seconds, 0=disable multi-turn | ⭐multi-turn |
| `DEEPSEEK_IMPERSONATE` | `chrome131` | curl_cffi TLS fingerprint profile | |
| `DEEPSEEK_JITTER_SECS` | `0.4` | random sleep seconds before a call | |
| `DEEPSEEK_RATE_LIMIT_RETRY_DELAYS` | `5,15` | upstream rate-limit backoff second list, empty=disable retries | |
| `LOG_LEVEL` | `INFO` | DEBUG/INFO/WARNING/ERROR | |
| `LOG_FORMAT` | `json` | json (production)/text (development) | |
| `ALLOWED_ORIGINS` | `""` | CORS allowed origins, comma-separated | browser clients |
| `ALLOW_CORS_CREDENTIALS` | `false` | credentialed cross-origin | |
| `TRUSTED_PROXIES` | `""` | trusted proxy IP/CIDR; XFF honored only when set | ⭐reverse proxy |
| `ALLOW_INSECURE_PUBLIC_DEFAULTS` | `false` | explicit confirmation of public + default password (not recommended) | |
| `DISABLE_AUTO_RECOVER` | `false` | disable account auto-recovery | |

**Configuration checklist for automation/proxy tools (in order):**
1. Create a client API key on the WebUI "Settings" page (otherwise `/v1/*` returns 503) → Bearer/x-api-key auth; legacy `API_KEYS` / `DEEPSEEK_API_KEY` are imported only on first initialization.
2. Account pool: add accounts via the WebUI, or write `data/accounts.json`; `.env` does not configure account credentials.
3. Public → `HOST=127.0.0.1` + reverse proxy + `TRUSTED_PROXIES`; or `HOST=0.0.0.0` + your own TLS/WAF.
4. The rate-limit defaults are fine; with multiple workers (gunicorn -w N) the effective limit = N × the configured value.
5. Changing `.env` requires **restarting the process** to take effect (load_dotenv is called only once at module load).


#### MODE details

| Value | Effect | model_type |
|----|------|-----------|
| `auto` | no forcing, uses client default behavior | `"default"` (quick mode) |
| `quick` | force quick mode | `"default"` |
| `expert` | force expert mode | `"expert"` |

#### THINKING details

| Value | Effect | thinking_enabled |
|----|------|-----------------|
| `auto` | decided by the request's `thinking_mode` | `req.thinking_mode or False` |
| `enabled` | force thinking on | `True` |
| `disabled` | force thinking off | `False` |

#### SEARCH details

| Value | Effect | search_enabled |
|----|------|---------------|
| `auto` | decided by the request's `search_enabled` | `req.search_enabled or False` |
| `enabled` | force web search on | `True` |
| `disabled` | force web search off | `False` |

**Important:** the three parameters are fully independent. `MODE=auto` is not the "old auto" — in the old version `thinking_mode=true` also set `model_type="expert"`. In the new version each dimension is controlled independently by its env var.

#### MODE / THINKING / SEARCH interaction matrix

| MODE | THINKING | SEARCH | Actual behavior |
|------|----------|--------|---------|
| `auto` | `auto` | `auto` | model_type="default", thinking=client, search=client |
| `auto` | `enabled` | `auto` | model_type="default", thinking=true, search=client |
| `auto` | `disabled` | `auto` | model_type="default", thinking=false, search=client |
| `quick` | `auto` | `auto` | model_type="default", thinking=client, search=client |
| `quick` | `enabled` | `auto` | model_type="default", thinking=true, search=client |
| `quick` | `disabled` | `disabled` | model_type="default", thinking=false, search=false |
| `expert` | `auto` | `auto` | model_type="expert", thinking=client, search=client |
| `expert` | `enabled` | `enabled` | model_type="expert", thinking=true, search=true |
| `expert` | `disabled` | `auto` | model_type="expert", thinking=false, search=client |

All 9 combinations are valid; `auto` means decided by the corresponding field in the client request.

After changing `.env` you must **restart the server** for it to take effect (`load_dotenv()` is called only once at module load).

### 13.2 Loading

```python
from dotenv import load_dotenv
load_dotenv()

MODEL_NAME = os.environ.get("MODEL_NAME", "deepseek-chat")
```

Account credentials are loaded by `AccountPool` from `data/accounts.json`, or managed via the WebUI; `adapter.py` must be given credentials explicitly at construction. `adapter.py` and `server.py` still call `load_dotenv()` to read other runtime config.

### 13.3 Getting the Token and Cookie

1. Open https://chat.deepseek.com and log in.
2. F12 → Network → any request.
3. Copy from the Request Headers:
   - `Authorization: Bearer <token>` → token
   - `Cookie: <full cookie>` → cookies

The Token and Cookie expire and must be refreshed periodically. Expiry signature: the PoW-challenge request returns `{"code":40003,"msg":"Authorization Failed (invalid token)"}`.

### 13.4 WASM binary source

`sha3_wasm_bg.wasm` is extracted from DeepSeek's frontend:

1. Open https://chat.deepseek.com and log in.
2. F12 → Sources → search `sha3_wasm_bg.wasm`.
3. Find the file in the "Network" tab and download it.
4. Or locate it directly in JS: the frontend loads `sha3_wasm_bg.wasm` via `wasm_bindgen`, usually paired with `sha3_wasm.js`.
5. Overwrite the file of the same name in the project root with the downloaded `.wasm`.

Verification:
```python
from wasmtime import Store, Module
with open("sha3_wasm_bg.wasm", "rb") as f:
    Module(Store().engine, f.read())
print("WASM valid")
```

**Risk notes:**
- DeepSeek may swap the WASM binary in any frontend update.
- After updating the WASM, check whether the exported function names changed.
- If `wasm_solve` and other exports are unavailable, update the `_WASMSolver` class accordingly.

### 13.5 httpx client config

```python
self._client = httpx.Client(timeout=120)
```

| Config | Value | Notes |
|--------|------|------|
| `timeout` | 120s | total connect + read + write timeout |
| Connection pool | default (10) | httpx default pool limit |
| Keep-Alive | enabled by default | reuse HTTP connections |

**Reason for the 120s timeout:**
- The expert-mode THINK phase can last 30-60s and needs enough waiting time.
- The DeepSeek server sends no data during long thinking, and a short timeout would misfire a disconnect.
- The web app's actual timeout is about 180s; 120s is a conservative value.
- `timeout=120` is the overall cap for all sub-timeouts (connect/read/write/pool).

With a short timeout (like the default 5s), expert mode would frequently disconnect during the thinking phase, showing up as `Server disconnected without sending a response`.

### 13.6 Port management and process control

`start.bat`'s port-management logic (combined with the `PORT` env var):

```batch
:: use the PORT env var (default 8080)
if "%PORT%"=="" set PORT=8080

:: find the LISTENING process on the configured port
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT% " ^| findstr LISTENING') do (
    taskkill /F /PID %%a
)
```

**How it works:**
1. Check the `PORT` env var, defaulting to 8080 if unset.
2. `netstat -ano` lists all connections and their PIDs.
3. `findstr ":%PORT% "` filters lines containing the configured port number.
4. `findstr LISTENING` keeps only the LISTENING state.
5. `tokens=5` extracts the 5th column (PID).
6. `taskkill /F /PID` force-terminates.

**Manual troubleshooting:**
```bash
# check the configured port
netstat -ano | findstr ":%PORT%"

# force-terminate a given PID
taskkill /F /PID <pid>
```

**`__pycache__` note:** if old behavior appears after a code update, Python may be caching old bytecode:
```bash
# clean all __pycache__
for /d /r . %d in (__pycache__) do @if exist "%d" rd /s /q "%d"
```
Consider adding the cleanup command to `start.bat` or your dev workflow.

---

## 15. Account Pool (AccountPool)

### 18.1 Design goals

Support round-robin use of multiple DeepSeek accounts, solving failover when a single account is rate-limited/banned. `AccountPool` manages an account's full lifecycle: add, allocate, release, error-mark, and health check.

### 18.2 Core data structure

```python
@dataclass
class Account:
    token: str            # DeepSeek Bearer Token
    cookies: str          # DeepSeek Cookie
    email: str            # display label
    state: str            # idle | busy | error
    error_count: int
    last_error: str
    last_used: float
```

### 18.3 State transitions

```
add → idle
        │
   acquire() → busy → release() → idle
        │                │
        │  mark_error()  ↓
        └────────→ error ──→ relogin() (success → idle, failure → error)
```

### 18.4 Round-robin allocation

`acquire()` iterates the account list with a round-robin strategy, returning the first `idle` account and marking it `busy`. If all accounts are busy, it returns `None` and server.py returns HTTP 503.

### 18.5 Health check and relogin

```python
def check_health(acct) -> bool:
    """Verify credential validity by creating a DeepSeek session."""
```

`relogin(index)` runs a health check on `error`-state accounts: on success it resets to `idle`, on failure it keeps the `error` state and updates `last_error`.

### 15.6 Thread safety

`AccountPool` uses a `threading.Lock` to protect all state-changing operations (CRUD, state switches). `_WASMSolver` has its own lock; the two locks cannot deadlock (no nested locking).

### 15.7 Initial load and configuration source

- **Sole account source**: loaded from `data/accounts.json` at startup; WebUI/Admin API add/edit/delete also persist to that file.
- `.env` does not load account credentials; `DeepSeekAdapter` requires the caller to pass token and cookies explicitly.
- When the account pool is empty, `acquire()` returns `None` and a request cannot select an upstream account; you must first add an account in the WebUI or populate `data/accounts.json`.

### 15.8 Non-interactive account-pool configuration (for proxies / automation)

> **Scenario**: configure multi-account round-robin for SDKs, scripts, curl, CI, proxies, and other automation that does **not** go through the WebUI panel.
> **Key point**: account credentials are configured only through the WebUI account pool or `data/accounts.json`. `.env` provides no account fallback; non-interactive deployments maintain `data/accounts.json` directly.

**Full `data/accounts.json` schema (v1 plaintext):**

```json
{
  "version": 1,
  "accounts": [
    {
      "id": "acc-001",
      "email": "acc-001",
      "token": "<DeepSeek Bearer token>",
      "cookies": "cf_clearance=xxx; session=yyy; ...",
      "created_at": 1781234567,
      "updated_at": 1781234567
    },
    {
      "id": "acc-002",
      "email": "acc-002",
      "token": "<token2>",
      "cookies": "<cookies2>",
      "created_at": 1781234567,
      "updated_at": 1781234567
    }
  ]
}
```

- Fields: `id` (optional, auto-generated by default), `email` (display label), `token`, `cookies` (both required), `created_at`/`updated_at` (optional, integer epoch seconds).
- `version`: `1` (plaintext) or `2` (Fernet-encrypted). Parsed as plaintext when absent.
- This file **must** be `chmod 600`, and its directory `700`. It contains plaintext DeepSeek token+cookie; a leak means account abuse.

**Non-interactive setup steps:**

```bash
# 1. write the account-pool file (can be script-generated)
cat > /path/to/project/data/accounts.json <<'JSON'
{"version":1,"accounts":[
  {"email":"acc-001","token":"<token>","cookies":"<cookies>"}
]}
JSON
chmod 600 /path/to/project/data/accounts.json
chmod 700 /path/to/project/data

# 2. optional: change the store path (defaults to data/accounts.json)
#    set in .env or an env var: ACCOUNT_STORE_PATH=/path/to/accounts.json

# 3. create an API key on the WebUI "Settings" page (required for non-interactive, else /v1/* returns 503)
#    the key hash is stored in data/api_keys.sqlite3; the plaintext is shown only once at creation

# 4. start
python -m uvicorn server:app --host 127.0.0.1 --port 8080
```

- **Encrypted storage (recommended for public)**: set `DEEPSEEK_ENCRYPTION_KEY` (Fernet 32B base64); on first startup the `version:1` plaintext is auto-migrated to `version:2` encrypted, leaving `accounts.json.v1.bak`. After that **do not hand-write a plaintext file** (detect_store_version would judge it v2 encrypted and, with no key, refuse to load).
- **Write timing**: write the file **before** the service starts, or call `POST /admin/api/accounts` (needs an admin token) at runtime. At startup `_load_persisted_accounts()` loads everything at once.

---

## 16. Admin Backend (Admin API)

### 19.1 Design overview

The admin backend has three parts:
1. **Admin API** (`admin.py`) — a FastAPI APIRouter mounted under the `/admin/api` prefix.
2. **AccountPool** (`account_pool.py`) — the account-pool core logic.
3. **Frontend SPA** (`webui-new/`) — a React SPA (v3.0.0+); the build artifacts `webui-new/dist/` are served by `server.py` under `/webui/*`.

All admin API endpoints (except `/admin/api/login`) require Bearer Token authentication.

### 19.2 API endpoints

| Method | Path | Notes |
|------|------|------|
| `POST` | `/admin/api/login` | password login, returns a token |
| `GET` | `/admin/api/stats` | request stats (total/success/failure/avg latency/tokens/uptime) |
| `GET` | `/admin/api/accounts` | account list + pool-status summary (total/idle/busy/error) |
| `POST` | `/admin/api/accounts` | add an account (body: token, cookies, email) |
| `DELETE` | `/admin/api/accounts/{index}` | delete an account |
| `POST` | `/admin/api/accounts/{index}/relogin` | relogin an error account |

### 19.3 Authentication mechanism

- Admin password: the `DEEPSEEK_ADMIN_PASSWORD` env var (default `admin`).
- Token storage: an in-memory `set` on the server; each login generates a 64-hex token.
- Token verification: extracted from the `Authorization: Bearer <token>` header on each request.
- No expiry (relogin needed after a service restart).

### 16.4 Request stats

`StatsSnapshot` maintains the following counters in memory:
- `total_requests` / `success_requests` / `failed_requests`
- `total_latency_ms` (accumulated, then averaged)
- `total_prompt_tokens` / `total_completion_tokens`
- Aggregated per model: `models[model_name] = {requests, prompt_tokens, completion_tokens}`

Stats are recorded via `get_stats().record()` before and after `chat()`/`chat_stream()` calls. Streaming responses ensure stats are recorded in a `finally` block.

### 16.5 Frontend SPA (v3.0.0+)

- **Stack**: Vite 5 + React 18 + TypeScript + shadcn/ui (Radix + Tailwind) + Recharts + Zustand + react-router-dom v6.
- **Routing**: `createBrowserRouter(..., { basename: '/webui' })` — the SPA lives at `/webui/*`; deep-link refreshes fall back to index.html via `server.py`'s `/webui/{rest}` SPA fallback.
- **Build**: `npm install && npm run build` under `webui-new/` (or `scripts/build.bat`), artifacts in `webui-new/dist/`. vite `base: '/webui/'` makes asset references carry the prefix (changing back to `/` causes JS/CSS 404 white screens).
- **Auth**: the admin token is stored in `localStorage` (zustand persist, key `ds2api-auth`); the `api()` wrapper uniformly attaches `Authorization: Bearer <admin-token>`, and a 401 auto-logs out and redirects to `/login`. `/v1/*` now also accepts this admin token (see 13.1/18.1).
- **Pages**: Login / Overview (stat cards + request-volume/latency Recharts + account-pool status) / Account Pool (table + drawer details + add/edit/delete + relogin) / Playground (streaming chat; parameters expose only the fields the backend actually forwards; reasoning shown collapsed) / Settings (`/admin/api/env`, read-only) / 404.
- **Theme**: light/dark/system, persisted in `localStorage` (key `ds2api-theme`); `main.tsx` calls `applyTheme` before mount to avoid a flash.
- **Polling**: on Overview, stats 5s / accounts 10s / history 30s; on Accounts, 10s (the `useApi` hook uses an AbortController + reqId to prevent races).

### 16.6 Integration with server.py

```python
# server.py
from admin import router as admin_router, get_pool, get_stats

pool = get_pool()           # the shared AccountPool instance

# use the pool to get an account in a handler
acq = pool.acquire()        # get an idle account (marked busy)
# ... use acq.adapter.chat_stream(...) ...
pool.release(acq.acct)      # release (marked back to idle)

# record stats after the request completes
get_stats().record(model, latency_ms, prompt_tokens, completion_tokens)
```

---

## 17. Key Algorithm Details

### 20.1 PoW token construction

```python
raw = json.dumps({
    "algorithm": "DeepSeekHashV1",
    "challenge": challenge_data["challenge"],
    "salt": challenge_data["salt"],
    "answer": nonce,
    "signature": challenge_data["signature"],
    "target_path": challenge_data["target_path"],
}, separators=(",", ":"))  # whitespace-free compaction
pow_token = base64.b64encode(raw.encode()).decode()
```

Note that `separators=(",", ":")` ensures the JSON has no whitespace, which is the format the DeepSeek server expects.

### 17.2 SSE line parsing

```python
for line in resp.iter_lines():
    line = line.strip()
    if not line: continue
    if line.startswith("event: "):
        current_event = line[7:]
        continue
    if line.startswith("data: "):
        data_str = line[6:]
        if not data_str: continue
        data = json.loads(data_str)
```

Key points:
- `line.strip()` removes leading/trailing whitespace (including `\r`).
- the `event:` line is an optional event-type label.
- a `data:` line may be followed by an empty string (skip it).
- lines that fail JSON parsing are skipped (non-critical path).

### 17.3 `_try_finish_capture` completion judgment

```python
def _is_capture_complete(self) -> bool:
    if "<|DSML|tool_calls>" in buf or "<tool_calls>" in buf:
        return "</|DSML|tool_calls>" in buf or "</tool_calls>" in buf
    if "<invoke " in buf or "<|DSML|invoke " in buf:
        return "</invoke>" in buf or "</|DSML|invoke>" in buf
    return False
```

It detects both the `|DSML|`-prefixed and the non-prefixed tag formats.

### 14.4 WASM memory operations

`_WASMSolver._encode(s)` writes a string into WASM linear memory:

```python
def _encode(self, s: str):
    data = s.encode("utf-8")
    ptr = self.malloc(self.store, len(data), 1)  # wasm allocate len(data) bytes
    mem = self.memory.data_ptr(self.store)
    for i, b in enumerate(data):
        mem[ptr + i] = b                         # copy byte by byte into WASM memory
    return ptr, len(data)
```

Key details:

| Operation | Notes |
|------|------|
| `self.malloc(len, 1)` | wasm-allocated `__wbindgen_export_0`, corresponding to `aligned_alloc`; align=1 means no alignment requirement |
| `mem[ptr + i] = b` | Python obtains a NumPy-like view of WASM linear memory via `memory.data_ptr` and writes directly |
| returns `(ptr, length)` | pointer + length are the two values passed to the wasm function |

Meaning of the `wasm_solve` call arguments:

```python
self.wasm_solve(
    self.store,
    stack_ptr,     # stack pointer (where the result goes)
    chal_ptr,      # challenge string pointer
    chal_len,      # challenge string length
    prefix_ptr,    # prefix string pointer = salt + "_" + expire_at + "_"
    prefix_len,    # prefix string length
    float(difficulty),  # difficulty converted to f64
)
```

Reading the result:

```python
ret = int.from_bytes(bytes(mem[stack_ptr:stack_ptr + 4]), byteorder='little', signed=True)
# ret == 0 → solve failed, raise PoWError
# ret != 0 → continue reading the nonce

result = struct.unpack('<d', bytes(mem[stack_ptr + 8:stack_ptr + 16]))[0]
# 8-byte f64, little-endian, i.e. the solved nonce
```

Stack layout (16 bytes):

```
stack_ptr + 0:  i32 (4 bytes) — success flag (0=failure, !=0=success)
stack_ptr + 4:  4 bytes padding
stack_ptr + 8:  f64 (8 bytes) — nonce value
```

### 14.5 The `role_sent` tracking in streaming responses

In `server.py`'s streaming handling, the SSE's initial events must be controlled:

```python
role_sent = False

# handle a thinking token
elif tt == "thinking":
    content = token.get("content", "")
    if content:
        if not role_sent:
            yield _openai_chunk(proxy_id, reasoning_content="")  # empty frame marking the start of thinking
            role_sent = True
        yield _openai_chunk(proxy_id, reasoning_content=content)
    continue

# handle a content token (via the sieve)
if not role_sent:
    if thinking_mode:
        yield _openai_chunk(proxy_id, reasoning_content="")  # emit the empty frame only in thinking mode
    role_sent = True
yield _openai_chunk(proxy_id, content=evt.data)
```

**Conditions for the empty `reasoning_content` frame:**

| Path | Emit empty frame? | Condition |
|------|-----------|------|
| Thinking token loop | ✅ always | already in the thinking branch; the empty frame marks "thinking start" |
| Text token loop | ✅ only when `thinking_mode=True` | a pure text stream with no thinking should not emit reasoning |
| Flush path | ✅ only when `thinking_mode=True` | same as above |
| Fallback path | ✅ only when `thinking_mode=True` | same as above |

**The `role_sent` flag becomes True after the first content send, and the initial frame is not sent again afterwards.**

#### The `finish_reason: "stop"` end frame

The end of a streaming response must send a `finish_reason: "stop"` end frame (`_openai_chunk(proxy_id, finish=True)`), otherwise the client cannot distinguish a normal completion from an abnormal disconnect.

```python
# end of stream
yield _openai_chunk(proxy_id, finish=True)  # delta: {}, finish_reason: "stop"
yield "data: [DONE]\n\n"
```

`_openai_chunk(proxy_id, finish=True)` yields:
```json
{"index": 0, "delta": {}, "finish_reason": "stop"}
```

Older versions lacked this frame, making the client treat the `finish_reason: null` of the last content chunk before `[DONE]` as the end signal, misjudging it as `finish: "other"`.

---

## 18. Known Limitations and Edge Cases

### 18.1 Authentication

- **Token/Cookie expiry**: expires irregularly and must be re-fetched. There is no auto-renewal (the webui account pool offers one-click relogin).
- **Account source**: managed only by the WebUI/Admin API and persisted to `data/accounts.json`, or by maintaining that file directly; `.env` does not load account credentials.
- **Two auth schemes**: `/v1/*` clients use an API key managed on the WebUI "Settings" page (Bearer or `x-api-key`, SQLite stores only the hash); the webui admin side exchanges `DEEPSEEK_ADMIN_PASSWORD` for an admin-session token. Legacy `API_KEYS` / `DEEPSEEK_API_KEY` are imported only when the key database is first created.
- **admin token admitted on `/v1/*`** (v2.2.0+ behavior): `_check_api_auth` first verifies `verify_admin_token()` and admits if valid — the webui uses the same token for the model list/Playground. Anyone holding an admin token already has full control of the account pool, so this does not widen the risk surface.
- **Login throttling**: 5 failures per IP / 300s window, returning 429 over the limit; the count is in-process memory and resets on restart.

### 18.2 Functional limitations

| Limitation | Reason | Impact |
|------|------|------|
| No parallel tool calls | DSML protocol limitation | only one tool at a time |
| `tool_choice` unreliable | prompt-injection approach limitation | the model may choose not to call a tool |
| `max_tokens` ineffective | DeepSeek API does not support it | long replies must be truncated yourself |
| `temperature`/`top_p` ineffective | DeepSeek API does not support them | cannot control randomness |
| Images only (no PDFs/docs) | only image upload is wired | images work via the vision upload flow; other file types would need the same `upload_file` path |
| OpenAI non-streaming endpoint does not output reasoning_content | the OpenAI non-streaming response model does not include this field | use streaming for the reasoning process (Anthropic non-streaming already supports thinking blocks) |

### 18.3 CORS cross-origin support

The project uses FastAPI's `CORSMiddleware` to handle cross-origin requests. The config is in `server.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Allows all origins, methods, and headers by default.** This solves the problem of browser extensions (like YouTube subtitle translation and other Chrome extensions) failing on the CORS preflight (`OPTIONS`) when using the OpenAI-compatible API. If deployed in an environment that must restrict cross-origin access, tighten `allow_origins` and so on accordingly.

### 18.4 Stability

- **WASM solve failure**: in rare cases the solve times out or returns 0, requiring a retry.
- **Session creation failure**: the PoW expired or the credentials are invalid.
- **SSE stream break**: a long response may be interrupted by DeepSeek.
- **DSML parse failure**: when the model's output does not match the expected format, the tool call does not take effect.

### 18.5 Edge-case handling

**Empty message list:** `_build_prompt([])` returns `""`, and DeepSeek may reply empty or error.

### 18.6 Stale bytecode cache (`__pycache__`)

Python's `__pycache__` directory caches compiled bytecode (`.pyc`). When the source is modified but the cache is not refreshed, `python server.py` may run old code.

**Triggers:**
- Starting directly after editing a code file.
- Having run before and `__pycache__` already exists.
- uvicorn's `--reload` mode detects file changes but does not clean `__pycache__`.

**Symptoms:**
- Behavior unchanged after a code edit.
- Debug print statements do not appear.
- Old bugs persist.
- Newly added functions throw `ImportError` or `NameError`.

**Troubleshooting:**
```bash
# compare .py and .pyc timestamps
dir /s __pycache__\*.pyc

# see the module path Python actually loads
python -c "import adapter; print(adapter.__file__)"
```

**Root fix:**
```bash
# delete all __pycache__ directories
for /d /r . %d in (__pycache__) do @if exist "%d" rd /s /q "%d"
```

**Prevention:**
- Use `--reload` mode during development.
- Add a `__pycache__` cleanup command at the end of `start.bat`.
- Manually delete `__pycache__` after editing code.

### 15.6 README.md

`README.md` exists and is kept in sync (v3.2.1 summary + quick start + API docs). Maintenance notes:
- When changing the README, keep the "v3.2.1 fixes" summary and quick start (startup/config/credential semantics) in sync.
- The start.bat behavior (auto venv/deps/WebUI build/auto-open browser) is described in the README; keep it in sync when changing the script.

### 15.7 Windows bash curl Chinese-encoding issue

In Windows bash (Git Bash), curl sending a JSON body containing Chinese may get the request rejected:

```bash
# may fail in Windows bash (returns a 422 Pydantic validation error)
curl -s -X POST ... -d '{"messages":[{"role":"user","content":"你好"}],"stream":true}'

# works with English
curl -s -X POST ... -d '{"messages":[{"role":"user","content":"hello"}],"stream":true}'
```

**Root cause:** Windows bash passes non-ASCII characters in command-line arguments with an encoding inconsistent with Python/FastAPI's JSON parser, causing Pydantic model validation to fail (`There was an error parsing the body`).

**Solutions:**
1. Test with ASCII-only content (`"hello"` instead of `"你好"`).
2. Write the JSON to a file and pass it with `-d @file.json`.
3. Use PowerShell's `Invoke-RestMethod`.
4. Use a GUI tool like Postman or Bruno.

This **does not affect real usage** — the user's tools/clients (OpenAI SDK, Claude Code, custom tools) send a UTF-8 JSON body via a standard HTTP POST and are not affected.

### 15.8 `.env` changes require a service restart

Both `server.py` and `adapter.py` call `load_dotenv()` at module load to read `.env`:

```python
# module level
load_dotenv()
MODE = os.environ.get("MODE", "auto").strip().lower()
THINKING = os.environ.get("THINKING", "auto").strip().lower()
```

This means **after changing `.env` you must restart the server** for it to take effect. Merely saving the file does not trigger a reload. In `--reload` mode uvicorn detects file changes and restarts, but `.env` changes are not within uvicorn's file watch — a manual restart is needed.


## 19. Common Debugging Methods

### 19.1 Test PoW and basic connectivity

```python
from adapter import DeepSeekAdapter, TOKEN, COOKIES
adapter = DeepSeekAdapter(token=TOKEN, cookies=COOKIES)
sid = adapter.create_session()
print(f"Session: {sid}")
```

Expected output: `Session: <uuid>`. On failure, check whether the credentials expired.

### 19.2 Test quick mode

```python
content = adapter.chat(sid, "User: Hello")
print(f"Reply: {content}")
```

### 19.3 Test expert mode

```python
content = adapter.chat(sid, "User: Think about a philosophy question",
                        thinking_enabled=True, search_enabled=False)
print(f"Reply: {content}")
```

### 16.4 Test expert-mode streaming

```python
for token in adapter.chat_stream(sid, "User: Hello",
                                  thinking_enabled=True):
    if isinstance(token, dict):
        if token.get("__type") == "thinking":
            print(f"[THINK] {token['content']}")
        elif token.get("__type") == "status":
            print(f"[STATUS] {token['status']}")
    else:
        print(token, end="")
```

### 16.5 Raw SSE capture

Modify `chat_stream()` or use the following snippet to print the raw SSE:

```python
resp = adapter._client.post(
    f"{BASE_URL}/api/v0/chat/completion", json=body, headers=headers)
for line in resp.iter_lines():
    print(line)
```

### 16.6 Quick test with curl

**Health check:**
```bash
curl http://localhost:8080/health
```

**Model list:**
```bash
curl http://localhost:8080/v1/models
```

**Non-streaming normal conversation:**
```bash
curl -X POST http://localhost:8080/v1/chat/completions ^
  -H "Content-Type: application/json" ^
  -d "{\"messages\":[{\"role\":\"user\",\"content\":\"hello\"}],\"stream\":false}"
```

**Streaming normal conversation:**
```bash
curl -X POST http://localhost:8080/v1/chat/completions ^
  -H "Content-Type: application/json" ^
  -d "{\"messages\":[{\"role\":\"user\",\"content\":\"hello\"}],\"stream\":true}"
```

**Expert mode (streaming):**
```bash
curl -X POST http://localhost:8080/v1/chat/completions ^
  -H "Content-Type: application/json" ^
  -d "{\"messages\":[{\"role\":\"user\",\"content\":\"think about a philosophy question\"}],\"stream\":true,\"thinking_mode\":true}"
```

**Tool call:**
```bash
curl -X POST http://localhost:8080/v1/chat/completions ^
  -H "Content-Type: application/json" ^
  -d "{\"messages\":[{\"role\":\"user\",\"content\":\"what's the weather in Beijing?\"}],\"tools\":[{\"type\":\"function\",\"function\":{\"name\":\"get_weather\",\"description\":\"get weather\",\"parameters\":{\"type\":\"object\",\"properties\":{\"city\":{\"type\":\"string\"}}}}]}"
```

### 16.7 Troubleshooting steps (in priority order)

A systematic troubleshooting flow when the service misbehaves:

1. **Health check** → does `/health` return `{"status":"ok"}`?
2. **Credential validity** → does `adapter.create_session()` succeed?
3. **PoW solving** → does the WASM load correctly?
4. **Quick mode** → does the most basic `adapter.chat(sid, "User: Hello")` return?
5. **Expert mode** → does `thinking_enabled=True` trigger the fragment state machine?
6. **Streaming output** → can `chat_stream()` yield token by token?
7. **Tool calls** → does StreamSieve correctly capture DSML tags?

### 16.8 Common errors

| Error message | Possible cause | Fix |
|---------|---------|------|
| `Authorization Failed (invalid token)` | Token expired | update .env |
| `Update to the latest version to use Expert` | X-App-Version too low | change to `20241129.1` |
| `WASM solver found no solution` | PoW difficulty too high / solve anomaly | retry |
| `Session creation failed` | PoW expired / invalid credentials | retry / update credentials |
| `Server disconnected without sending a response` | DeepSeek server timeout or httpx timeout too short | check timeout=120; retry |
| `data: {"type":"error","content":"..."}` | DeepSeek business error | troubleshoot by the content |
| Behavior unchanged after a code edit | stale `__pycache__` cache | delete the `__pycache__` directory |
| `ImportError: cannot import name 'X' from 'adapter'` | stale module cache | delete `__pycache__` and restart |
| `PoWError: WASM solver found no solution` | incompatible WASM binary | check the wasmtime version or re-extract the WASM |
| Process exited but the port is still held | the previous uvicorn did not fully terminate | find the PID with `netstat -ano | findstr :<PORT>` then taskkill |

### 16.9 Analyzing with HAR

1. Browser F12 → Network → export HAR.
2. Parse with `jq` or Python:
```python
import json
with open("file.har") as f:
    har = json.load(f)
for entry in har["log"]["entries"]:
    url = entry["request"]["url"]
    if "chat/completion" in url:
        print(url, entry["request"]["postData"]["text"])
```

---

## 20. Protocol Change Warnings

The following factors may break the project and need timely updates:

### 20.1 Frontend updates

A DeepSeek frontend update may change:
- API endpoint paths (`/api/v0/chat/completion` → something else)
- request-body field names/formats
- SSE event structure
- the PoW algorithm or challenge format
- request-header requirements

**Detection**: periodically capture the latest HAR with the browser DevTools and compare.

### 17.2 WASM updates

`sha3_wasm_bg.wasm` may be updated by DeepSeek:
- exported-function name changes
- solver-algorithm changes
- difficulty-algorithm adjustments

**Detection**: check the `algorithm` field in the `create_pow_challenge` response.

### 17.3 Anti-scraping upgrades

DeepSeek may introduce new anti-scraping mechanisms:
- extra signature/encryption headers
- a JS Challenge (like Cloudflare)
- request-frequency limits
- IP blocking

### 17.4 Maintenance strategy

1. **Capture regularly** (at least monthly).
2. **HAR comparison**: save a baseline HAR file and compare differences.
3. **Degradation plan**: when expert mode fails, at least keep quick mode working.
4. **Capture focus**:
   - Focus on the two core endpoints `chat_session/create` and `chat/completion`.
   - Record all request headers, especially custom ones starting with `X-`.
   - Record the SSE event sequence, noting new `p` paths or `o` operations.
   - Watch for changes in the enum values of the `model_type` field.

### 17.5 WASM binary update procedure

A DeepSeek frontend update may change the WASM binary. Full update procedure:

```bash
# Step 1: extract the new WASM from the DeepSeek frontend
# Method A: browser DevTools → Network → search "sha3_wasm_bg.wasm" → download
# Method B: locate the wasm load point in JS
#   open chat.deepseek.com → F12 → Sources
#   search "sha3_wasm_bg.wasm" to find the loading code

# Step 2: overwrite the old file
copy /y new_sha3_wasm_bg.wasm sha3_wasm_bg.wasm

# Step 3: verify the exports
python -c "
from wasmtime import Store, Module, Instance
with open('sha3_wasm_bg.wasm', 'rb') as f:
    module = Module(Store().engine, f.read())
instance = Instance(Store(), module, [])
exports = instance.exports(Store())
print('Exports:', list(exports.keys()))
print('has wasm_solve:', 'wasm_solve' in exports)
print('has memory:', 'memory' in exports)
"

# Step 4: test PoW solving
python -c "
from adapter import DeepSeekAdapter, TOKEN, COOKIES
a = DeepSeekAdapter(token=TOKEN, cookies=COOKIES)
c = a._get_challenge()
print('Challenge solved')
"

# Step 5: test a full conversation
python -c "
from adapter import DeepSeekAdapter, TOKEN, COOKIES
a = DeepSeekAdapter(token=TOKEN, cookies=COOKIES)
sid = a.create_session()
r = a.chat(sid, 'User: Hello')
print('Reply:', r[:100])
"
```

**Change-detection script** (recommended to run regularly):
```python
import hashlib
old_hash = "the known old file SHA256"  # record on first run
with open("sha3_wasm_bg.wasm", "rb") as f:
    new_hash = hashlib.sha256(f.read()).hexdigest()
if new_hash != old_hash:
    print("WARNING: WASM binary has changed!")
    print(f"Old: {old_hash}")
    print(f"New: {new_hash}")
```

---

> Document last updated: 2026-08-08
> Based on `chat.deepseek.com` HAR capture analysis (2026-05-06)
> WASM engine version: `sha3_wasm_bg.wasm` (extracted from the DeepSeek frontend, with `__wbindgen_export_0` malloc / `__wbindgen_export_1` realloc / `__wbindgen_export_2` free)
> Protocol version: DeepSeek Chat v2.0.0 (X-Client-Version)
