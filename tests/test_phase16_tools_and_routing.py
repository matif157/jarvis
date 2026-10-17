"""Phase 16 — Missing-tool wiring + routing/execution correctness tests.

Covers:
  * task.*/memory.*/web.* registered in the enhanced registry
  * web tools work offline (mock provider)
  * task.reopen / task.cancel no longer raise NameError
  * Router decides only (no execution side effects)
  * ActionLoop is the single executor (exactly-once)
  * confirmation gating for destructive tools (interactive vs. non-interactive)
"""

import asyncio
import builtins

from jarvis.tools import Tool, ToolResult, ToolRegistry, get_enhanced_registry


class CounterTool(Tool):
    name = "counter.tool"
    description = "Counts executions"
    permissions = []
    calls = 0

    def run(self, **kwargs):
        CounterTool.calls += 1
        return ToolResult(success=True, result=CounterTool.calls, tool=self.name)


class DestructiveTool(Tool):
    name = "destructive.tool"
    description = "Requires confirmation"
    permissions = ["file.delete"]
    calls = 0

    def run(self, **kwargs):
        DestructiveTool.calls += 1
        return ToolResult(success=True, result="deleted", tool=self.name)


class _StubLLM:
    def __init__(self, reply):
        self.reply = reply

    async def active_provider(self):
        return "stub"

    async def complete(self, messages, temperature=0.0):
        return self.reply, "stub"


class _DummyRouter:
    """Placeholder whose .route is replaced per-test."""


# 1
def test_registry_has_new_tools():
    reg = get_enhanced_registry()
    names = {t["name"] for t in reg.list_tools()}
    for expected in (
        "task.add",
        "task.list",
        "task.complete",
        "task.reopen",
        "task.cancel",
        "memory.remember",
        "memory.recall",
        "memory.list",
        "memory.forget",
        "web.search",
        "web.research",
    ):
        assert expected in names, f"missing tool: {expected}"
    assert len(names) >= 80, len(names)
    print(f"✓ Test 1 PASSED: registry exposes new tools ({len(names)} total)")


# 2
def test_web_search_tool_offline():
    reg = get_enhanced_registry()
    res = reg.execute("web.search", query="jarvis self test")
    assert res.success, res.error
    assert isinstance(res.result, dict)
    assert res.result.get("results"), "expected mock results"
    print("✓ Test 2 PASSED: web.search returns offline results")


# 3
def test_web_research_tool_offline():
    reg = get_enhanced_registry()
    res = reg.execute("web.research", question="what is jarvis?")
    assert res.success, res.error
    assert res.result.get("report")
    print("✓ Test 3 PASSED: web.research returns a report")


# 4
def test_get_web_tools():
    from jarvis.web_search import get_web_tools

    tools = get_web_tools()
    assert len(tools) == 2, [t.name for t in tools]
    print("✓ Test 4 PASSED: get_web_tools returns 2 tools")


# 5
def test_task_reopen_and_cancel_no_datetime_error():
    reg = ToolRegistry()
    from jarvis import tools as T

    reg.register(T.TaskAddTool())
    reg.register(T.TaskReopenTool())
    reg.register(T.TaskCancelTool())

    added = reg.execute("task.add", title="phase16 reopen/cancel probe")
    assert added.success, added.error
    tid = added.result["id"]

    reopened = reg.execute("task.reopen", task_id=tid)
    assert reopened.success, reopened.error
    assert reopened.result["status"] == "pending"

    cancelled = reg.execute("task.cancel", task_id=tid)
    assert cancelled.success, cancelled.error
    assert cancelled.result["status"] == "cancelled"
    print("✓ Test 5 PASSED: task.reopen/task.cancel execute without NameError")


# 6
def test_router_decides_without_executing():
    from jarvis.router import Router

    reg = ToolRegistry()
    reg.register(CounterTool())
    CounterTool.calls = 0
    router = Router(registry=reg, llm_module=_StubLLM('{"tool": "counter.tool", "args": {}}'))

    decision = asyncio.run(router.route("do the thing"))
    assert decision["kind"] == "tool"
    assert decision["tool"] == "counter.tool"
    assert CounterTool.calls == 0, "router must NOT execute tools"
    print("✓ Test 6 PASSED: Router decides only (no execution)")


# 7
def test_action_loop_executes_exactly_once():
    from jarvis.action_loop import ActionLoop

    reg = ToolRegistry()
    reg.register(CounterTool())
    CounterTool.calls = 0
    al = ActionLoop(registry=reg, router=_DummyRouter())

    state = {"n": 0}

    async def route(*a, **k):
        state["n"] += 1
        if state["n"] == 1:
            return {"kind": "tool", "tool": "counter.tool", "args": {}}
        return {"kind": "chat", "text": "done", "provider": "stub"}

    al.router.route = route
    res = asyncio.run(al.run("count once"))
    assert res["kind"] == "chat"
    assert CounterTool.calls == 1, f"expected 1 execution, got {CounterTool.calls}"
    assert len(res["steps"]) == 1
    print("✓ Test 7 PASSED: tool executed exactly once by ActionLoop")


# 7b
def test_destructive_non_interactive_requires_confirmation():
    from jarvis.action_loop import ActionLoop

    reg = ToolRegistry()
    reg.register(DestructiveTool())
    DestructiveTool.calls = 0

    async def route(*a, **k):
        return {"kind": "tool", "tool": "destructive.tool", "args": {}}

    loop = ActionLoop(registry=reg, router=_DummyRouter(), interactive=False)
    loop.router.route = route
    res = asyncio.run(loop.run("delete everything"))
    assert DestructiveTool.calls == 0, "destructive tool must not run without confirmation"
    assert "confirmation" in res["text"].lower(), res["text"]
    print("✓ Test 7b PASSED: non-interactive destructive tool is gated")


# 8
def test_interactive_confirmation_approves():
    from jarvis.action_loop import ActionLoop

    reg = ToolRegistry()
    reg.register(DestructiveTool())
    DestructiveTool.calls = 0

    state = {"n": 0}

    async def route(*a, **k):
        state["n"] += 1
        if state["n"] == 1:
            return {"kind": "tool", "tool": "destructive.tool", "args": {}}
        return {"kind": "chat", "text": "done", "provider": "fake"}

    loop = ActionLoop(registry=reg, router=_DummyRouter(), interactive=True)
    loop.router.route = route
    original_input = builtins.input
    builtins.input = lambda *a, **k: "y"
    try:
        asyncio.run(loop.run("delete it"))
    finally:
        builtins.input = original_input
    assert DestructiveTool.calls == 1, "approved destructive tool should run once"
    print("✓ Test 8 PASSED: interactive confirmation approves execution")


# 9
def test_permissions_allowlist_scopes():
    from jarvis.permissions import DEFAULT_ALLOWLIST

    for scope in ("web.research", "task.read", "task.write", "memory.read", "memory.write", "note.read", "note.write"):
        assert scope in DEFAULT_ALLOWLIST, f"missing scope: {scope}"
    print("✓ Test 9 PASSED: allowlist scopes present")


# 10
def test_assistant_interactive_flag():
    from jarvis.assistant import Assistant

    assert Assistant(mode="basic").interactive is False
    assert Assistant(mode="basic", interactive=True).interactive is True
    assert Assistant(mode="basic", interactive=True).action_loop.interactive is True
    print("✓ Test 10 PASSED: Assistant propagates interactive flag")
