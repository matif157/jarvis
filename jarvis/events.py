"""Agent timeline events for the transparent agent UI.

A tiny, dependency-free pub/sub layer used to stream *what the assistant is
doing* (routing, tool calls, results, the final message) to clients such as the
web Agent Console. Events are plain dicts shaped as ``{"type": "...", ...}``.

The emitter is intentionally permissive: instrumentation must never be able to
break the actual assistant work, so handler errors are swallowed.
"""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable, Dict, Optional

# Event type constants (kept as plain strings so events stay JSON-serialisable).
EVT_START = "start"
EVT_THOUGHT = "thought"
EVT_CONFIRMATION = "confirmation"
EVT_TOOL_CALL = "tool_call"
EVT_TOOL_RESULT = "tool_result"
EVT_MESSAGE = "message"
EVT_ERROR = "error"
EVT_DONE = "done"

EventHandler = Callable[[Dict[str, Any]], Any]


def make_event(event_type: str, **fields: Any) -> Dict[str, Any]:
    """Build an event dict with the given type and fields."""
    return {"type": event_type, **fields}


class EventEmitter:
    """Forwards events to an optional sync-or-async handler.

    When ``handler`` is ``None`` the emitter is a cheap no-op, so callers can
    always ``await emitter.emit(...)`` without branching.
    """

    def __init__(self, handler: Optional[EventHandler] = None):
        self.handler = handler

    @property
    def enabled(self) -> bool:
        return self.handler is not None

    async def emit(self, event_type: str, **fields: Any) -> None:
        if self.handler is None:
            return
        event = make_event(event_type, **fields)
        try:
            result = self.handler(event)
            if inspect.isawaitable(result):
                await result
        except Exception:  # noqa: BLE001 - instrumentation must not break work
            pass


# Shared no-op emitter for code paths that do not stream.
NULL_EMITTER = EventEmitter(None)


__all__ = [
    "EVT_START",
    "EVT_THOUGHT",
    "EVT_CONFIRMATION",
    "EVT_TOOL_CALL",
    "EVT_TOOL_RESULT",
    "EVT_MESSAGE",
    "EVT_ERROR",
    "EVT_DONE",
    "EventHandler",
    "make_event",
    "EventEmitter",
    "NULL_EMITTER",
]
