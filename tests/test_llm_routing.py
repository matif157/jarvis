"""Phase 1 — LLM routing tests."""
import asyncio
import os

from jarvis import assistant, llm, router
from jarvis.tools import Tool, ToolResult, ToolRegistry


class FakeTool(Tool):
    name = "fake.echo"
    description = "Echo back the provided text"
    permissions = []

    def run(self, text="", **kwargs):
        return ToolResult(success=True, result=f"echo:{text}", tool=self.name)


def make_registry():
    reg = ToolRegistry()
    reg.register(FakeTool())
    reg.register_function("time.now", lambda: "2026-01-01T00:00:00", "Get current time")
    return reg


def async_ret(value):
    async def _f(*a, **k):
        return value
    return _f


def fake_complete(text, provider="fake"):
    async def _complete(messages, **kwargs):
        _complete.calls.append(messages)
        return text, provider
    _complete.calls = []
    return _complete


def silence_db(monkeypatch):
    monkeypatch.setattr(assistant.db, "save_message", lambda *a, **k: None)
