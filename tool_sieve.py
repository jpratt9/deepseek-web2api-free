"""
StreamSieve — streaming sieve engine

Detects DSML tool-call tags character by character, separating body text from
tool calls in real time out of the SSE stream.

v2.2.0 fixes:
* ``feed()`` no longer recurses on suffix tail; replaced with iterative loop.
* ``_split_safe()`` no longer holds an empty tail forever.
* ``_capture_buf`` has a hard size cap (configurable via
  ``DSML_MAX_BUFFER_BYTES``) to prevent unbounded growth from adversarial
  or malformed model output.
"""
import os
from dataclasses import dataclass
from typing import Any, Callable


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(1024, int(raw))  # never allow less than 1 KiB
    except ValueError:
        return default


MAX_CAPTURE_BUFFER = _env_int("DSML_MAX_BUFFER_BYTES", 1024 * 1024)  # 1 MiB


@dataclass
class SieveEvent:
    type: str  # 'text' | 'tool_calls'
    data: Any


class StreamSieve:
    """Sieve DSML tool calls out of the SSE stream in real time."""

    _TOOL_STARTS = [
        "<|DSML|tool_calls>",
        "|DSML|tool_calls>",
        "<tool_calls>",
        "<tool_call>",
        "<invoke ",
        "<|DSML|invoke ",
        "|DSML|invoke ",
    ]

    # Plain prefixes that *could* grow into a tool call tag. Used to decide
    # how much of the tail to hold while we wait for more characters.
    _TOOL_PREFIXES = (
        "<|DSML|", "|DSML|", "<tool_calls", "<tool_call", "<invoke",
    )

    def __init__(self, parse_fn: Callable | None = None,
                 max_capture_buffer: int | None = None):
        self.parse_fn = parse_fn
        self._pending = ""
        self._capture_buf = ""
        self._capturing = False
        self._max_capture_buffer = (
            max_capture_buffer if max_capture_buffer is not None
            else MAX_CAPTURE_BUFFER
        )

    def feed(self, chunk: str) -> list[SieveEvent]:
        events: list[SieveEvent] = []
        if not chunk:
            return events
        if self._capturing:
            self._capture_buf += chunk
            if len(self._capture_buf) > self._max_capture_buffer:
                # Force-flush: the model is producing far more than a single
                # tool call; treat the buffer as plain text and recover.
                events.append(SieveEvent("text", self._capture_buf))
                self._capture_buf = ""
                self._capturing = False
                return events
            result = self._try_finish_capture()
            if result is not None:
                prefix, tool_calls, suffix = result
                if prefix:
                    events.append(SieveEvent("text", prefix))
                if tool_calls:
                    events.append(SieveEvent("tool_calls", tool_calls))
                # Iterative instead of recursive — Python's stack is finite
                # and a long suffix with many tool calls would blow it.
                if suffix:
                    self._pending = suffix
                self._capture_buf = ""
                self._capturing = False
                if suffix:
                    events.extend(self._drain_pending())
            return events

        self._pending += chunk
        start_idx = self._find_tool_start(self._pending)

        if start_idx >= 0:
            prefix = self._pending[:start_idx]
            rest = self._pending[start_idx:]
            self._pending = ""
            if prefix:
                events.append(SieveEvent("text", prefix))
            self._capture_buf = rest
            self._capturing = True
            result = self._try_finish_capture()
            if result is not None:
                prefix_text, tool_calls, suffix = result
                if prefix_text:
                    events.append(SieveEvent("text", prefix_text))
                if tool_calls:
                    events.append(SieveEvent("tool_calls", tool_calls))
                if suffix:
                    self._pending = suffix
                self._capture_buf = ""
                self._capturing = False
                if suffix:
                    events.extend(self._drain_pending())
        else:
            safe, hold = self._split_safe(self._pending)
            if safe:
                events.append(SieveEvent("text", safe))
            self._pending = hold

        return events

    def _drain_pending(self) -> list[SieveEvent]:
        """Iteratively process the pending buffer without recursion."""
        events: list[SieveEvent] = []
        while self._pending:
            if self._capturing:
                # Capture is set elsewhere; this branch shouldn't be hit
                # in the iterative path, but be defensive.
                break
            start_idx = self._find_tool_start(self._pending)
            if start_idx >= 0:
                prefix = self._pending[:start_idx]
                rest = self._pending[start_idx:]
                self._pending = ""
                if prefix:
                    events.append(SieveEvent("text", prefix))
                self._capture_buf = rest
                self._capturing = True
                result = self._try_finish_capture()
                if result is not None:
                    p, tcs, sfx = result
                    if p:
                        events.append(SieveEvent("text", p))
                    if tcs:
                        events.append(SieveEvent("tool_calls", tcs))
                    if sfx:
                        self._pending = sfx
                    self._capture_buf = ""
                    self._capturing = False
                    # Loop continues with any new pending.
                else:
                    break
            else:
                safe, hold = self._split_safe(self._pending)
                if safe:
                    events.append(SieveEvent("text", safe))
                self._pending = hold
                # If hold is empty, we're done. If it isn't, the next
                # chunk will resolve it; we just stop the loop now to
                # avoid spinning.
                break
        return events

    def flush(self) -> list[SieveEvent]:
        events: list[SieveEvent] = []
        if self._capturing:
            result = self._try_finish_capture()
            if result is not None:
                prefix, tool_calls, suffix = result
                if prefix:
                    events.append(SieveEvent("text", prefix))
                if tool_calls:
                    events.append(SieveEvent("tool_calls", tool_calls))
                if suffix:
                    events.append(SieveEvent("text", suffix))
            else:
                # Not closed; treat as body text
                events.append(SieveEvent("text", self._capture_buf))
            self._capture_buf = ""
            self._capturing = False
        if self._pending:
            events.append(SieveEvent("text", self._pending))
            self._pending = ""
        return events

    def _find_tool_start(self, text: str) -> int:
        for tag in self._TOOL_STARTS:
            pos = text.find(tag)
            if pos >= 0:
                return pos
        for prefix in self._TOOL_PREFIXES:
            pos = text.find(prefix)
            if pos >= 0:
                return pos
        return -1

    def _split_safe(self, text: str) -> tuple[str, str]:
        """Return ``(safe, hold)`` such that ``safe + hold == text`` and
        ``hold`` is the smallest suffix that could still grow into a
        DSML tool-call tag.
        """
        if not text:
            return "", ""
        # Hold from the EARLIEST '<' or '|' whose tail can still grow into a
        # tag. Looking only at the last special character breaks when the
        # model streams "<|DSML|tool_calls>" in small pieces: with "<|" held,
        # the last special char is '|', so the '<' was emitted as text and the
        # capture started at "|DSML|...". The client then saw a stray "<"
        # before every streamed tool call, plus a leaked closing tag.
        cands = (*self._TOOL_STARTS, *self._TOOL_PREFIXES)
        for i in range(max(0, len(text) - max(map(len, cands))), len(text)):
            if text[i] in "<|" and any(c.startswith(text[i:]) for c in cands):
                return text[:i], text[i:]
        return text, ""

    def _try_finish_capture(self):
        if not self._capture_buf or not self.parse_fn:
            return None
        if not self._is_capture_complete():
            return None
        tool_calls, cleaned = self.parse_fn(self._capture_buf)
        if tool_calls:
            return ("", tool_calls, "")
        return (self._capture_buf, None, "")

    def _is_capture_complete(self) -> bool:
        buf = self._capture_buf
        if "<|DSML|tool_calls>" in buf or "<tool_calls>" in buf:
            return "</|DSML|tool_calls>" in buf or "</tool_calls>" in buf
        if "<invoke " in buf or "<|DSML|invoke " in buf:
            return "</invoke>" in buf or "</|DSML|invoke>" in buf
        return False
