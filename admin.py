"""Admin API — stats tracking, account pool management, env display.

No auth: this proxy runs on localhost, so the panel is open to local callers.
"""
import os
import time
from collections import deque

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from account_pool import AccountPool
from crypto import is_enabled as crypto_is_enabled, _resolve_key
from logger import get_logger
from stats_history import get_history

log = get_logger("admin")

SERVER_VERSION = "4.0.0"

# ── Stats ─────────────────────────────────────────────────────
_LATENCY_WINDOW_SIZE = 1024


def _percentile(values: list[float], pct: float) -> int:
    if not values:
        return 0
    sorted_v = sorted(values)
    k = max(0, min(len(sorted_v) - 1, int(round((pct / 100.0) * (len(sorted_v) - 1)))))
    return int(sorted_v[k])


class StatsSnapshot:
    def __init__(self):
        self.reset()

    def reset(self):
        self.total_requests = 0
        self.success_requests = 0
        self.failed_requests = 0
        self.total_latency_ms = 0.0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.start_time = time.time()
        self.models: dict[str, dict] = {}
        self._recent_latencies: deque[float] = deque(maxlen=_LATENCY_WINDOW_SIZE)

    def record(self, model: str, latency_ms: float,
               prompt_tokens: int = 0, completion_tokens: int = 0,
               success: bool = True):
        self.total_requests += 1
        if success:
            self.success_requests += 1
            if latency_ms > 0:
                self._recent_latencies.append(float(latency_ms))
        else:
            self.failed_requests += 1
        self.total_latency_ms += latency_ms
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        if model not in self.models:
            self.models[model] = {"requests": 0, "prompt_tokens": 0,
                                  "completion_tokens": 0, "errors": 0}
        self.models[model]["requests"] += 1
        self.models[model]["prompt_tokens"] += prompt_tokens
        self.models[model]["completion_tokens"] += completion_tokens
        if not success:
            self.models[model]["errors"] += 1

    def percentile(self, pct: float) -> int:
        return _percentile(list(self._recent_latencies), pct)

    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.success_requests / self.total_requests


_stats = StatsSnapshot()
_pool = AccountPool()


def get_pool() -> AccountPool:
    return _pool


def get_stats() -> StatsSnapshot:
    return _stats


# ── Pydantic models ───────────────────────────────────────────
class AccountAddRequest(BaseModel):
    token: str
    cookies: str
    email: str | None = ""


class AccountUpdateRequest(BaseModel):
    token: str | None = None
    cookies: str | None = None
    email: str | None = None


class AccountReloginResponse(BaseModel):
    ok: bool
    message: str


# ── Router ────────────────────────────────────────────────────
router = APIRouter(prefix="/admin/api")


def _pool_error(e: Exception):
    if isinstance(e, KeyError):
        raise HTTPException(status_code=404, detail=str(e).strip("'"))
    if isinstance(e, PermissionError):
        raise HTTPException(status_code=400, detail=str(e))
    if isinstance(e, RuntimeError):
        raise HTTPException(status_code=409, detail=str(e))
    if isinstance(e, ValueError):
        raise HTTPException(status_code=400, detail=str(e))
    raise e


@router.get("/stats")
async def stats():
    s = _stats
    uptime = int(time.time() - s.start_time)
    avg_latency = int(s.total_latency_ms / s.total_requests) if s.total_requests > 0 else 0
    return {
        "total_requests": s.total_requests,
        "success_requests": s.success_requests,
        "failed_requests": s.failed_requests,
        "success_rate": round(s.success_rate(), 4),
        "avg_latency_ms": avg_latency,
        "p50_latency_ms": s.percentile(50),
        "p95_latency_ms": s.percentile(95),
        "p99_latency_ms": s.percentile(99),
        "latency_window_size": len(s._recent_latencies),
        "total_prompt_tokens": s.total_prompt_tokens,
        "total_completion_tokens": s.total_completion_tokens,
        "uptime_secs": uptime,
        "models": s.models,
    }


@router.get("/history")
async def history():
    """Rolling time-series of the stats, for the overview charts."""
    h = get_history()
    return {"interval_secs": h.interval(), "points": h.points()}


@router.get("/env")
async def env_info():
    """Read-only view of the effective runtime configuration (Settings page)."""
    def _env(name: str, default: str = "") -> str:
        return os.environ.get(name, default)

    crypto_on = crypto_is_enabled()
    names = ["HOST", "PORT", "MODE", "THINKING", "SEARCH", "MODEL_NAME",
             "ACCOUNT_STORE_PATH", "DEEPSEEK_ENCRYPTION_KEY", "DEEPSEEK_IMPERSONATE",
             "DEEPSEEK_JITTER_SECS", "DEEPSEEK_MAX_CONCURRENCY",
             "DEEPSEEK_RATE_LIMIT_RETRY_DELAYS", "LOG_LEVEL", "LOG_FORMAT",
             "STATS_HISTORY_INTERVAL_SECS"]
    overrides = []
    for n in names:
        raw = os.environ.get(n)
        value = "***" if (n == "DEEPSEEK_ENCRYPTION_KEY" and crypto_on) else (raw or "")
        overrides.append({"name": n, "value": value, "is_default": raw is None})

    return {
        "host": _env("HOST", "127.0.0.1"),
        "port": int(_env("PORT", "8080") or 8080),
        "accounts_total": _pool.count(),
        "crypto": {"enabled": crypto_on, "fernet_configured": bool(_resolve_key())},
        "log_level": _env("LOG_LEVEL", "INFO").upper(),
        "log_format": _env("LOG_FORMAT", "json").lower(),
        "uptime_secs": int(time.time() - _stats.start_time),
        "server_version": SERVER_VERSION,
        "env_overrides": overrides,
    }


@router.get("/accounts")
async def list_accounts():
    return {"accounts": _pool.get_all(), **_pool.stats()}


@router.post("/accounts")
async def add_account(req: AccountAddRequest):
    try:
        acct = _pool.add(token=req.token, cookies=req.cookies, email=req.email or "")
    except Exception as e:
        _pool_error(e)
    return {"ok": True, "account": acct.to_dict()}


@router.put("/accounts/{account_id}")
async def update_account(account_id: str, req: AccountUpdateRequest):
    try:
        acct = _pool.update(account_id, token=req.token, cookies=req.cookies, email=req.email)
    except Exception as e:
        _pool_error(e)
    return {"ok": True, "account": acct.to_dict()}


@router.delete("/accounts/{account_id}")
async def remove_account(account_id: str):
    try:
        ok = _pool.remove_by_id(account_id)
    except Exception as e:
        _pool_error(e)
    if not ok:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"ok": True}


@router.post("/accounts/{account_id}/relogin")
async def relogin_account(account_id: str) -> AccountReloginResponse:
    ok, msg = _pool.relogin_by_id(account_id)
    return AccountReloginResponse(ok=ok, message=msg)
