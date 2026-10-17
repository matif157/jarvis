# Phase 16 — Missing-Tool Wiring & Routing Correctness Report

Date: 2026-10-17
Version: v1.0.0 → **v1.0.1**

## Goal

Close the gaps found while reviewing "what can Jarvis actually do": tools that
existed in code but were not registered, a runtime `NameError`, a double
execution bug, and a few stale/duplicated routing paths.

## What was wrong

1. `get_enhanced_registry()` never registered `task.*` or `memory.*` tools, and
   `web_search.py` had no `Tool` wrappers, so the assistant could not use them.
2. `TaskReopenTool` / `TaskCancelTool` referenced `datetime` without importing
   it → `NameError` when run.
3. **Double execution**: `Router.route` executed the chosen tool, and then
   `ActionLoop.run` executed it again (two side effects for one request).
4. `Assistant.respond` called `self.router.route(...)` a second time as a
   fallback — redundant and confusing.
5. `SYSTEM_PROMPT` advertised a stale hard-coded tool list (`time.now, echo`).
6. Destructive tools were never actually gated in the loop (confirmation was
   computed but not applied to `registry.execute`).

## Changes

| Area | File | Change |
| --- | --- | --- |
| Registry | `jarvis/tools.py` | Deduped; registered `task.*` (5) + `memory.*` (4); fixed `datetime` import; correct macOS class names; joins `get_web_tools()`. 69 → **80** tools. |
| Web | `jarvis/web_search.py` | Added `WebSearchTool`, `WebResearchTool`, `get_web_tools()` (offline mock). |
| Routing | `jarvis/router.py` | `route()` is **decide-only**; removed execution + `_summarise`. |
| Loop | `jarvis/action_loop.py` | Single executor; `interactive` mode with `input()` confirmation; non-interactive destructive calls surface `confirmation required`. |
| Assistant | `jarvis/assistant.py` | `interactive` flag; removed duplicated router fallback; refreshed `SYSTEM_PROMPT`. |
| CLI | `jarvis/cli.py` | `chat`/`start` construct `Assistant(..., interactive=True)`. |
| Permissions | `jarvis/permissions.py` | Added `web.research`, `note.*`, `task.*`, `memory.*` scopes. |

## Verification

- `tests/test_phase16_tools_and_routing.py` — 11 offline checks:
  registry contents, offline web tools, `task.reopen`/`task.cancel`,
  router-decides-only, exactly-once loop execution, confirmation gating
  (interactive approve + non-interactive decline), allowlist scopes,
  interactive flag propagation.
- Full suite: **317 passed, 0 failed across 30 modules**.
- Live checks (Ollama `llama3.2:1b`):
  - `Router.route("What is the exact current date and time?")` →
    `{"kind": "tool", "tool": "time.now", "provider": "ollama"}` with **no**
    `result` key (decide-only confirmed).
  - `Assistant(mode="llm").respond("Use the time tool …")` → `time.now`
    executed **once**, final answer produced by the LLM continuing on the
    tool result.

## Status

`IMPLEMENTED` / `UNIT-TESTED` / `INTEGRATION-TESTED` (Ollama live).

## Notes / Follow-ups

- `PermissionManager.is_allowed()` still ignores the allowlist patterns (only
  `deny` is honored). Left unchanged deliberately — it is load-bearing across
  the codebase and changing it needs its own reviewed phase.
- `web.search`/`web.research` are offline (mock provider) until a real provider
  is configured; results are labelled as such.
