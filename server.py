"""OpenAI-compatible API proxy for DeepSeek Chat (minimal).

Text chat only, served out of an account pool. Endpoints:
  GET  /health
  GET  /v1/models
  POST /v1/chat/completions   (stream + non-stream)
  /admin/api/*                (account pool, stats, env — see admin.py)
  /webui/*                    (the React panel)
"""
import json
import os
import threading
import time
import uuid
from typing import Optional, Union
import os as _os

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel

from adapter import (
    UpstreamEmptyError,
    UpstreamHintError,
    RateLimitError,
)
from admin import router as admin_router, get_pool, get_stats
from stats_history import start_sampler
from logger import get_logger, configure_from_env
from token_counter import count_text

load_dotenv()
configure_from_env()
log = get_logger("server")

MODEL_NAME = os.environ.get("MODEL_NAME", "deepseek-chat")
MODE = os.environ.get("MODE", "auto").strip().lower()
THINKING = os.environ.get("THINKING", "auto").strip().lower()
SEARCH = os.environ.get("SEARCH", "auto").strip().lower()
HOST = os.environ.get("HOST", "127.0.0.1").strip()
PORT = int(os.environ.get("PORT", "8080"))

# Models offered to clients / the Playground. `deepseek-reasoner` selects
# expert (reasoning) mode; anything else is quick mode (unless MODE forces it).
_MODELS = ["deepseek-chat", "deepseek-reasoner"]

app = FastAPI(title="DeepSeek Chat API", version="4.0.0")

pool = get_pool()
start_sampler(get_stats())
if pool.count() == 0:
    log.warning("no_accounts_in_pool",
                extra={"hint": "Add an account in the WebUI or data/accounts.json"})


# ---- Upstream concurrency cap ----
def _upstream_limit_from_env() -> int:
    try:
        return max(1, int(os.environ.get("DEEPSEEK_MAX_CONCURRENCY", "2")))
    except ValueError:
        return 2


_UPSTREAM_LIMITER = threading.BoundedSemaphore(_upstream_limit_from_env())


# ---- Pydantic models ----
class ContentPart(BaseModel):
    type: str
    text: Optional[str] = None


class ChatMessage(BaseModel):
    role: str
    content: Optional[Union[str, list[ContentPart]]] = None


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = MODEL_NAME
    messages: list[ChatMessage]
    stream: Optional[bool] = False
    # Accepted for client compatibility but not forwarded to DeepSeek.
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    thinking_mode: Optional[bool] = False
    search_enabled: Optional[bool] = False


# ---- Account pool ----
class AcquiredAccount:
    def __init__(self, acct):
        self.acct = acct
        self.adapter = acct.adapter
        self._released = False

    def create_session(self) -> str:
        return self.adapter.create_session()

    def release(self):
        if self._released:
            return
        self._released = True
        pool.release(self.acct)
        _UPSTREAM_LIMITER.release()


def _acquire() -> AcquiredAccount:
    # Cap simultaneous upstream calls so parallel clients don't flood DeepSeek
    # (which triggers account mutes). Queued requests wait for a slot.
    _UPSTREAM_LIMITER.acquire()
    try:
        acct = pool.acquire()
    except Exception:
        _UPSTREAM_LIMITER.release()
        raise
    if acct is None:
        _UPSTREAM_LIMITER.release()
        raise HTTPException(status_code=503, detail="All accounts busy, try again later")
    return AcquiredAccount(acct)


# ---- Prompt building (text only) ----
def _extract_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return " ".join(p.text for p in content if p.type == "text" and p.text)


def _build_prompt(messages: list[ChatMessage]) -> str:
    parts = []
    for m in messages:
        if m.role == "system":
            text = _extract_text(m.content)
            if text:
                parts.append(f"System: {text}")
        elif m.role == "user":
            parts.append(f"User: {_extract_text(m.content)}")
        elif m.role == "assistant":
            text = _extract_text(m.content)
            if text:
                parts.append(f"Assistant: {text}")
    return "\n".join(parts)


def _resolve_modes(model: str | None, req: "ChatCompletionRequest"):
    """model_type / thinking / search from the model name + MODE/THINKING/SEARCH."""
    if (model or "").strip() == "deepseek-reasoner" or MODE == "expert":
        model_type = "expert"
    else:
        model_type = "default"
    if THINKING == "enabled":
        thinking = True
    elif THINKING == "disabled":
        thinking = False
    else:
        thinking = req.thinking_mode or False
    if SEARCH == "enabled":
        search = True
    elif SEARCH == "disabled":
        search = False
    else:
        search = req.search_enabled or False
    return model_type, thinking, search


# ---- OpenAI SSE helpers ----
def _openai_chunk(proxy_id, content="", finish=False, reasoning_content=None, role=None):
    delta = {}
    if not finish:
        if role:
            delta["role"] = role
        if reasoning_content is not None:
            delta["reasoning_content"] = reasoning_content
        elif content:
            delta["content"] = content
    chunk = {
        "id": proxy_id, "object": "chat.completion.chunk",
        "created": int(time.time()), "model": MODEL_NAME,
        "choices": [{"index": 0, "delta": delta,
                     "finish_reason": "stop" if finish else None}],
    }
    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"


# ---- Endpoints ----
@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/v1/models")
async def list_models():
    return {"object": "list", "data": [
        {"id": name, "object": "model", "created": int(time.time()), "owned_by": "deepseek"}
        for name in _MODELS
    ]}


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest):
    proxy_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    prompt = _build_prompt(req.messages)
    model_type, thinking, search = _resolve_modes(req.model, req)
    if req.stream:
        return await _handle_stream(proxy_id, prompt, model_type, thinking, search)
    return _handle_nonstream(proxy_id, prompt, model_type, thinking, search)


def _handle_nonstream(proxy_id, prompt, model_type, thinking_mode, search_enabled):
    prompt_tokens = count_text(prompt)
    acq = _acquire()
    try:
        ds_id = acq.create_session()
        t0 = time.time()
        content, thinking = acq.adapter.chat(
            ds_id, prompt, model_type=model_type,
            thinking_enabled=thinking_mode, search_enabled=search_enabled)
        completion_tokens = count_text(content) + count_text(thinking)
        get_stats().record(MODEL_NAME, (time.time() - t0) * 1000,
                           prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    except RateLimitError as e:
        get_stats().record(MODEL_NAME, 0, success=False)
        raise HTTPException(status_code=429, detail=f"Upstream rate limited: {e.args[0] if e.args else 'requests too frequent'}. Please retry later.")
    except UpstreamHintError as e:
        get_stats().record(MODEL_NAME, 0, success=False)
        pool.mark_error(acq.acct, str(e))
        raise HTTPException(status_code=502, detail=str(e))
    except UpstreamEmptyError:
        get_stats().record(MODEL_NAME, 0, success=False)
        raise HTTPException(status_code=502, detail="Upstream returned an empty response (may be rate limited); please retry later.")
    except Exception as e:
        get_stats().record(MODEL_NAME, 0, success=False)
        pool.mark_error(acq.acct, str(e))
        raise
    finally:
        acq.release()

    total = prompt_tokens + count_text(content)
    return {
        "id": proxy_id, "object": "chat.completion",
        "created": int(time.time()), "model": MODEL_NAME,
        "choices": [{"index": 0,
                     "message": {"role": "assistant", "content": content},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt_tokens,
                  "completion_tokens": count_text(content),
                  "total_tokens": total},
    }


async def _handle_stream(proxy_id, prompt, model_type, thinking_mode, search_enabled):
    prompt_tokens = count_text(prompt)
    acq = _acquire()
    try:
        ds_id = acq.create_session()
    except Exception as e:
        get_stats().record(MODEL_NAME, 0, success=False, prompt_tokens=prompt_tokens)
        pool.mark_error(acq.acct, str(e))
        acq.release()
        raise
    t0 = time.time()

    async def event_stream():
        completion_parts: list[str] = []
        try:
            yield _openai_chunk(proxy_id, finish=False)
            role_sent = False
            for token in acq.adapter.chat_stream(
                    ds_id, prompt, model_type=model_type,
                    thinking_enabled=thinking_mode, search_enabled=search_enabled):
                if isinstance(token, dict):
                    tt = token.get("__type")
                    if tt == "status":
                        if token["status"] == "FINISHED":
                            break
                        continue
                    if tt == "thinking":
                        content = token.get("content", "")
                        if content:
                            completion_parts.append(content)
                            if not role_sent:
                                yield _openai_chunk(proxy_id, reasoning_content="", role="assistant")
                                role_sent = True
                            yield _openai_chunk(proxy_id, reasoning_content=content)
                        continue
                # plain text token
                if token:
                    completion_parts.append(token)
                    if not role_sent:
                        if thinking_mode:
                            yield _openai_chunk(proxy_id, reasoning_content="")
                        yield _openai_chunk(proxy_id, content=token, role="assistant")
                        role_sent = True
                    else:
                        yield _openai_chunk(proxy_id, content=token)

            yield _openai_chunk(proxy_id, finish=True)
            yield "data: [DONE]\n\n"
            get_stats().record(MODEL_NAME, (time.time() - t0) * 1000,
                               prompt_tokens=prompt_tokens,
                               completion_tokens=count_text("".join(completion_parts)))
        except Exception as e:
            get_stats().record(MODEL_NAME, (time.time() - t0) * 1000, success=False,
                               prompt_tokens=prompt_tokens)
            if not isinstance(e, (RateLimitError, UpstreamEmptyError)):
                pool.mark_error(acq.acct, str(e))
            log.exception("stream_failed")
            err = {
                "id": proxy_id, "object": "chat.completion.chunk",
                "created": int(time.time()), "model": MODEL_NAME,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "error"}],
                "error": {"type": "upstream_error", "message": str(e)[:500]},
            }
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            acq.release()

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


# ---- Admin + static webui ----
app.include_router(admin_router)

_WEBUI_DIR = _os.path.realpath(_os.path.join(_os.path.dirname(__file__), "webui-new", "dist"))


def _safe_webui_path(rest_of_path: str):
    """Resolve a path inside the webui dir, refusing traversal."""
    if not rest_of_path or "\x00" in rest_of_path:
        return None
    candidate = _os.path.realpath(_os.path.join(_WEBUI_DIR, rest_of_path))
    try:
        if _os.path.commonpath([candidate, _WEBUI_DIR]) != _WEBUI_DIR:
            return None
    except ValueError:
        return None
    return candidate if _os.path.isfile(candidate) else None


def _webui_index_path():
    index = _os.path.join(_WEBUI_DIR, "index.html")
    return index if _os.path.isfile(index) else None


@app.get("/webui/{rest_of_path:path}")
async def webui_spa(rest_of_path: str):
    safe = _safe_webui_path(rest_of_path)
    if safe is not None:
        return FileResponse(safe)
    index = _webui_index_path()
    if index is not None:
        return FileResponse(index)
    return {"error": "webui not built — run `npm run build` in webui-new/"}


@app.get("/webui")
async def webui_root():
    index = _webui_index_path()
    if index is not None:
        return FileResponse(index)
    return {"error": "webui not built — run `npm run build` in webui-new/"}


if __name__ == "__main__":
    uvicorn.run("server:app", host=HOST, port=PORT, reload=False)
