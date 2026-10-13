"""Phase 2 — Action loop tests."""

from jarvis import action_loop, assistant
from jarvis.tools import Tool, ToolResult, ToolRegistry


class FakeTool(Tool):
    name = "fake.echo"
    description = "Echo"
    permissions = []

    def run(self, text="", **kwargs):
        return ToolResult(success=True, result=f"echo:{text}", tool=self.name)


class FakeToolFail(Tool):
    name = "fake.fail"
    description = "Fail"
    permissions = []

    def run(self, **kwargs):
        return ToolResult(success=False, error="boom", tool=self.name)


def make_registry():
    reg = ToolRegistry()
    reg.register(FakeTool())
    reg.register(FakeToolFail())
    return reg


async def chat_decision(*a, **k):
    return {"kind": "chat", "text": "done", "provider": "fake"}


async def tool_then_chat(*a, **k):
    if not hasattr(tool_then_chat, "calls"):
        tool_then_chat.calls = 0
    tool_then_chat.calls += 1
    if tool_then_chat.calls == 1:
        return {"kind": "tool", "tool": "fake.echo", "args": {"text": "hi"}, "text": "will do"}
    return {"kind": "chat", "text": "ok", "provider": "fake"}


async def tool_fail(*a, **k):
    return {"kind": "tool", "tool": "fake.fail", "args": {}, "text": "fail"}


def test_single_shot_chat(monkeypatch):
    reg = make_registry()
    al = action_loop.ActionLoop(registry=reg, router=type("R", (), {})())
    al.router.route = chat_decision
    import asyncio

    res = asyncio.run(al.run("hi"))
    assert res["kind"] == "chat"
    assert res["text"] == "done"


def test_tool_then_chat(monkeypatch):
    reg = make_registry()
    al = action_loop.ActionLoop(registry=reg, router=type("R", (), {})())
    tool_then_chat.calls = 0
    al.router.route = tool_then_chat
    import asyncio

    res = asyncio.run(al.run("echo hi"))
    assert res["kind"] == "chat"
    assert res["text"] == "ok"
    assert len(res["steps"]) == 1
    assert res["steps"][0]["tool"] == "fake.echo"


def test_tool_fails(monkeypatch):
    reg = make_registry()
    al = action_loop.ActionLoop(registry=reg, router=type("R", (), {})())
    al.router.route = tool_fail
    import asyncio

    res = asyncio.run(al.run("bad"))
    assert res["kind"] == "chat"
    assert "boom" in res["text"]
