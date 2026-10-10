"""Unit tests for DeepSeekAdapter parsing / retry logic (no network).

Covers the hint / toast error scanning, the empty-response retry, and
the rate-limit backoff retry added in v3.2.1. All upstream traffic is
mocked — nothing in this file touches the network.
"""
import time

import pytest

import adapter as A
from adapter import (
    DeepSeekAdapter,
    RateLimitError,
    UpstreamHintError,
    UpstreamEmptyError,
)


class _FakeResp:
    """Minimal stand-in for a curl_cffi Response (non-streaming)."""

    def __init__(self, text: str = ""):
        self.text = text

    @property
    def status_code(self) -> int:
        return 200

    @property
    def headers(self) -> dict:
        return {}

    def raise_for_status(self):
        pass


class _FakeStreamResp(_FakeResp):
    """Streaming stand-in whose iter_lines yields the SSE lines."""

    def iter_lines(self):
        for line in self.text.splitlines():
            yield line.encode("utf-8")

    def iter_content(self):
        yield self.text.encode("utf-8")


def _adapter():
    return DeepSeekAdapter(token="test-token", cookies="test-cookie")


# ── hint / toast scanning ─────────────────────────────────────

class TestHintScanning:
    def test_rate_limit_hint_raises_rate_limit_error(self):
        ad = _adapter()
        sse = (
            "event: ready\ndata: {\"request_message_id\":1}\n\n"
            "event: hint\n"
            "data: {\"type\":\"error\",\"content\":\"消息发送过于频繁，请稍后重试\","
            "\"finish_reason\":\"rate_limit_reached\"}\n\n"
            "event: close\ndata: {}\n\n"
        )
        events = ad._parse_sse(sse)
        hint = ad._scan_hint_errors(events)
        assert hint is not None
        assert hint[1] == "rate_limit_reached"
        with pytest.raises(RateLimitError):
            ad._raise_hint_error(hint[0], hint[1])

    def test_other_hint_raises_upstream_hint_error(self):
        ad = _adapter()
        sse = (
            "event: hint\n"
            "data: {\"type\":\"error\",\"content\":\"some error\",\"finish_reason\":\"other\"}\n\n"
        )
        events = ad._parse_sse(sse)
        hint = ad._scan_hint_errors(events)
        assert hint is not None
        with pytest.raises(UpstreamHintError):
            ad._raise_hint_error(hint[0], hint[1])

    def test_normal_sse_has_no_hint(self):
        ad = _adapter()
        sse = (
            "event: ready\ndata: {\"request_message_id\":1}\n\n"
            "data: {\"v\":\"normal\"}\n\n"
        )
        events = ad._parse_sse(sse)
        assert ad._scan_hint_errors(events) is None

    def test_toast_error_is_scanned(self):
        ad = _adapter()
        sse = (
            "event: toast\n"
            "data: {\"type\":\"error\",\"content\":\"使用专家模式请更新至最新版本\","
            "\"finish_reason\":\"unsupported_client_by_model\"}\n\n"
        )
        events = ad._parse_sse(sse)
        toast = ad._scan_toast_errors(events)
        assert toast is not None
        assert toast[1] == "unsupported_client_by_model"


# ── chat() non-streaming retry ────────────────────────────────

class TestChatRetry:
    def test_retries_once_on_empty_response(self, monkeypatch):
        ad = _adapter()
        calls = {"n": 0}

        def fake_send(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                return _FakeResp("")
            return _FakeResp(
                "event: ready\ndata: {\"request_message_id\":1}\n\n"
                "data: {\"v\":\"normal\"}\n\n"
            )

        monkeypatch.setattr(ad, "_send_completion", fake_send)
        monkeypatch.setattr(ad, "create_session", lambda: "sess-2")
        content, _ = ad.chat("sess-1", "prompt")
        assert content == "normal"
        assert calls["n"] == 2

    def test_raises_after_two_empty_responses(self, monkeypatch):
        ad = _adapter()
        monkeypatch.setattr(ad, "_send_completion",
                            lambda *a, **k: _FakeResp(""))
        monkeypatch.setattr(ad, "create_session", lambda: "sess-2")
        with pytest.raises(UpstreamEmptyError):
            ad.chat("sess-1", "prompt")

    def test_nonempty_sse_without_content_retries(self, monkeypatch):
        """SSE with no content tokens and no hint is treated as empty and
        retried once (defense against stale pooled connections)."""
        ad = _adapter()
        calls = {"n": 0}
        empty_sse = (
            "event: ready\ndata: {\"request_message_id\":1}\n\n"
            "event: update_session\ndata: {}\n\n"
            "data: {\"p\":\"response/status\",\"o\":\"SET\",\"v\":\"FINISHED\"}\n\n"
            "event: close\ndata: {}\n\n"
        )

        def fake_send(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                return _FakeResp(empty_sse)
            return _FakeResp(
                "event: ready\ndata: {\"request_message_id\":1}\n\n"
                "data: {\"v\":\"retry content\"}\n\n"
            )

        monkeypatch.setattr(ad, "_send_completion", fake_send)
        monkeypatch.setattr(ad, "create_session", lambda: "sess-2")
        content, _ = ad.chat("sess-1", "prompt")
        assert content == "retry content"
        assert calls["n"] == 2

    def test_rate_limit_backoff_then_success(self, monkeypatch):
        ad = _adapter()
        calls = {"n": 0}
        sleeps = []

        def fake_send(*a, **k):
            calls["n"] += 1
            if calls["n"] < 3:
                return _FakeResp(
                    "event: hint\n"
                    "data: {\"type\":\"error\",\"content\":\"频繁\","
                    "\"finish_reason\":\"rate_limit_reached\"}\n\n"
                )
            return _FakeResp(
                "event: ready\ndata: {\"request_message_id\":1}\n\n"
                "data: {\"v\":\"ok\"}\n\n"
            )

        monkeypatch.setattr(ad, "_send_completion", fake_send)
        monkeypatch.setattr(ad, "create_session", lambda: "sess-new")
        monkeypatch.setattr(A.time, "sleep", lambda s: sleeps.append(s))
        content, _ = ad.chat("sess-1", "prompt")
        assert content == "ok"
        assert calls["n"] == 3
        assert sleeps == [5.0, 15.0]  # default DEEPSEEK_RATE_LIMIT_RETRY_DELAYS

    def test_rate_limit_backoff_exhausted_raises(self, monkeypatch):
        ad = _adapter()
        monkeypatch.setattr(ad, "_send_completion",
                            lambda *a, **k: _FakeResp(
                                "event: hint\n"
                                "data: {\"type\":\"error\",\"content\":\"频繁\","
                                "\"finish_reason\":\"rate_limit_reached\"}\n\n"))
        monkeypatch.setattr(ad, "create_session", lambda: "sess-new")
        monkeypatch.setattr(A.time, "sleep", lambda s: None)
        with pytest.raises(RateLimitError):
            ad.chat("sess-1", "prompt")


# ── chat_stream() streaming retry + inline hint ───────────────

class TestChatStream:
    def test_empty_stream_retries_with_fresh_session(self, monkeypatch):
        ad = _adapter()
        calls = {"n": 0}

        def fake_post(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                return _FakeStreamResp("")  # empty body -> empty stream
            return _FakeStreamResp(
                "event: ready\ndata: {\"request_message_id\":1}\n\n"
                "data: {\"v\":\"streaming content\"}\n\n"
            )

        monkeypatch.setattr(ad, "_pow_headers", lambda *a, **k: {})
        monkeypatch.setattr(ad, "_client", type("C", (), {"post": fake_post})())
        monkeypatch.setattr(ad, "create_session", lambda: "sess-2")
        tokens = list(ad.chat_stream("sess-1", "prompt"))
        assert "streaming content" in tokens
        assert calls["n"] == 2

    def test_inline_hint_raises_rate_limit_error(self, monkeypatch):
        ad = _adapter()
        resp = _FakeStreamResp(
            "event: ready\ndata: {\"request_message_id\":1}\n\n"
            "event: hint\n"
            "data: {\"type\":\"error\",\"content\":\"消息发送过于频繁，请稍后重试\","
            "\"finish_reason\":\"rate_limit_reached\"}\n\n"
            "event: close\ndata: {}\n\n"
        )

        monkeypatch.setattr(ad, "_pow_headers", lambda *a, **k: {})
        monkeypatch.setattr(ad, "_client", type("C", (), {"post": lambda *a, **k: resp})())
        monkeypatch.setattr(ad, "create_session", lambda: "sess-2")
        monkeypatch.setattr(A.time, "sleep", lambda s: None)
        with pytest.raises(RateLimitError):
            list(ad.chat_stream("sess-1", "prompt"))


# ── hif signature headers ─────────────────────────────────────

class _FakeHifResp:
    def __init__(self, value: str | None, ttl: str = "600", status: int = 200):
        self.status_code = status
        self.headers = {"x-hif-ttl": ttl}
        self._value = value

    def json(self):
        if self._value is None:
            return {"data": {"biz_data": {}}}
        return {"data": {"biz_data": {"value": self._value}}}


class TestHifProvider:
    def test_fetches_and_caches_values(self):
        def get(self, url, timeout=10):
            return _FakeHifResp("leim-val" if "leim" in url else "dliq-val")

        client = type("C", (), {"get": get})()
        provider = A._HifProvider(client=client)
        hdrs = provider.headers()
        assert hdrs["X-Hif-Leim"] == "leim-val"
        assert hdrs["X-Hif-Dliq"] == "dliq-val"

    def test_cache_hits_do_not_refetch(self):
        calls = []

        def get(self, url, timeout=10):
            calls.append(url)
            return _FakeHifResp("val")

        client = type("C", (), {"get": get})()
        provider = A._HifProvider(client=client)
        provider.headers()
        provider.headers()
        assert calls.count(A.HIF_LEIM_URL) == 1
        assert calls.count(A.HIF_DLIQ_URL) == 1

    def test_failure_degrades_to_empty_headers(self):
        def get(url, timeout=10):
            raise RuntimeError("network down")

        client = type("C", (), {"get": get})()
        provider = A._HifProvider(client=client)
        assert provider.headers() == {}

    def test_stale_value_reused_on_refresh_failure(self, monkeypatch):
        client = type("C", (), {
            "get": lambda self, url, timeout=10: _FakeHifResp("good")
        })()
        provider = A._HifProvider(client=client)
        assert provider.headers()["X-Hif-Leim"] == "good"
        # Now break the fetcher but keep the cached value (not expired yet).
        provider._cache["leim"] = ("good", time.time() + 600)
        provider._fetch = lambda url: None
        assert provider.headers()["X-Hif-Leim"] == "good"

    def test_pow_headers_attach_hif_but_create_session_does_not(self, monkeypatch):
        ad = _adapter()
        monkeypatch.setattr(ad, "_get_challenge", lambda *a, **k: {"challenge": "c"})
        monkeypatch.setattr(ad, "_solve", lambda *a, **k: "nonce")
        monkeypatch.setattr(A.time, "sleep", lambda s: None)
        fake_hif = type("H", (), {
            "headers": lambda self: {"X-Hif-Leim": "L", "X-Hif-Dliq": "D"}
        })()
        monkeypatch.setattr(ad, "_hif", fake_hif)

        completion_hdrs = ad._pow_headers("/api/v0/chat/completion")
        assert completion_hdrs["X-Hif-Leim"] == "L"
        assert completion_hdrs["X-Hif-Dliq"] == "D"

        # create_session path must NOT carry hif headers
        create_hdrs = ad._pow_headers("/api/v0/chat/completion", include_hif=False)
        assert "X-Hif-Leim" not in create_hdrs
