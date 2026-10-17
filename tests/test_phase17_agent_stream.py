"""Phase 17 — Transparent agent timeline (events + SSE stream) tests.

Offline only: no network, no live providers. Uses mode="basic" for endpoints.
"""

import asyncio
import json

from fastapi.testclient import TestClient

from jarvis import action_loop, assistant, events
from jarvis.app import app
from jarvis.tools import Tool, ToolRegistry, ToolResult


def client():
    return TestClient(app)


class FakeTool(Tool):
    name = "fake.echo"
    description = "Echo"
    permissions = []

    def run(self, text="", **kwargs):
        return ToolResult(success=True, result=f"echo:{text}", tool=self.name)


def make_registry():
    reg = ToolRegistry()
    reg.register(FakeTool())
    return reg


async def tool_then_chat(*a, **k):
    if not hasattr(tool_then_chat, "calls"):
        tool_then_chat.calls = 0
    tool_then_chat.calls += 1
    if tool_then_chat.calls == 1:
        return {"kind": "tool", "tool": "fake.echo", "args": {"text": "hi"}, "text": ""}
    return {"kind": "chat", "text": "ok", "provider": "fake"}


def _parse_sse(text):
    out = []
    for line in text.splitlines():
        if line.startswith("data: "):
            out.append(json.loads(line[len("data: "):]))
    return out


# 1
def test_emitter_noop_without_handler():
    em = events.EventEmitter(None)
    assert em.enabled is False
    asyncio.run(em.emit("anything", x=1))  # must not raise
    print("✓ Test 1 PASSED: EventEmitter is a no-op without a handler")


# 2
def test_emitter_forwards_to_sync_handler():
    seen = []
    em = events.EventEmitter(seen.append)
    asyncio.run(em.emit(events.EVT_THOUGHT, text="hi"))
    assert seen == [{"type": "thought", "text": "hi"}]
    print("✓ Test 2 PASSED: EventEmitter forwards events to a sync handler")


# 3
def test_emitter_awaits_async_handler():
    seen = []

    async def handler(ev):
        seen.append(ev)

    em = events.EventEmitter(handler)
    asyncio.run(em.emit(events.EVT_MESSAGE, text="yo", provider="fake"))
    assert seen and seen[0]["type"] == "message" and seen[0]["provider"] == "fake"
    print("✓ Test 3 PASSED: EventEmitter awaits an async handler")


# 4
def test_emitter_swallows_handler_errors():
    def boom(_ev):
        raise RuntimeError("handler exploded")

    em = events.EventEmitter(boom)
    asyncio.run(em.emit(events.EVT_START))  # must not raise
    print("✓ Test 4 PASSED: EventEmitter never lets instrumentation break work")


# 5
def test_action_loop_emits_tool_events():
    reg = make_registry()
    al = action_loop.ActionLoop(registry=reg, router=type("R", (), {})())
    tool_then_chat.calls = 0
    al.router.route = tool_then_chat

    seen = []

    async def handler(ev):
        seen.append(ev)

    res = asyncio.run(al.run("echo hi", on_event=handler))
    assert res["kind"] == "chat" and res["text"] == "ok"
    types = [e["type"] for e in seen]
    assert events.EVT_THOUGHT in types
    assert events.EVT_TOOL_CALL in types
    assert events.EVT_TOOL_RESULT in types
    call = next(e for e in seen if e["type"] == events.EVT_TOOL_CALL)
    assert call["tool"] == "fake.echo" and call["args"] == {"text": "hi"}
    result = next(e for e in seen if e["type"] == events.EVT_TOOL_RESULT)
    assert result["success"] is True and result["result"] == "echo:hi"
    assert "duration_ms" in result
    print("✓ Test 5 PASSED: ActionLoop emits thought/tool_call/tool_result")


# 6
def test_assistant_respond_emits_start_and_message():
    a = assistant.Assistant(mode="basic")
    seen = []

    async def handler(ev):
        seen.append(ev)

    text, provider, _tool = asyncio.run(a.respond("hello", on_event=handler))
    types = [e["type"] for e in seen]
    assert types[0] == events.EVT_START
    assert events.EVT_MESSAGE in types
    msg = next(e for e in seen if e["type"] == events.EVT_MESSAGE)
    assert msg["text"] == text and msg["provider"] == provider
    print("✓ Test 6 PASSED: Assistant.respond emits start + message events")


# 7
def test_agent_stream_endpoint_streams_offline():
    with client() as c:
        r = c.get("/api/agent/stream", params={"message": "hello", "mode": "basic"})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        evs = _parse_sse(r.text)
        types = [e["type"] for e in evs]
        assert types[0] == "start"
        assert "message" in types
        assert types[-1] == "done"
        msg = next(e for e in evs if e["type"] == "message")
        assert isinstance(msg["text"], str) and msg["text"].strip()
    print("✓ Test 7 PASSED: /api/agent/stream emits start…message…done")


# 8
def test_chat_endpoint_still_works():
    with client() as c:
        r = c.post("/api/chat", json={"message": "hi", "mode": "basic"})
        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "basic" and body["text"].strip()
    print("✓ Test 8 PASSED: legacy /api/chat still works (backward compatible)")


# 9
def test_index_has_agent_console_tab():
    with client() as c:
        html = c.get("/").text
        for tab in ("Chat", "Agent", "Tools", "Settings"):
            assert tab in html
        assert "agent-log" in html and "console-input" in html
    print("✓ Test 9 PASSED: index page serves Chat + Agent + Tools + Settings")


# 10
def test_static_assets_expose_agent_stream():
    with client() as c:
        js = c.get("/static/app.js").text
        css = c.get("/static/style.css").text
        assert "/api/agent/stream" in js
        assert "EventSource" in js
        assert "api/chat" in js  # graceful fallback path retained
        assert ".agent-log" in css and ".chat-log" in css
    print("✓ Test 10 PASSED: static assets expose the agent console + stream")
