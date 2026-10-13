# Phase 1 Report — Real LLM in Normal Chat + LLM Tool Routing

Date: 2026-10-13
Repo: /Users/husayn/Documents/Default Project/jarvis
Branch: phase-1-llm-routing   Commit: <sha>
Environment: Python 3.9.6, Ollama http://127.0.0.1:11434, model llama3.2:1b

## Scope
Phase 1: normal chat uses real LLM with local-first routing; LLM can select a single registered tool (single-shot). No multi-step loops, confirmations, or native tool_calls (deferred to Phase 2).

## What Changed
- jarvis/llm.py: added active_provider() (local-first readiness check; prefers ollama when up)
- jarvis/router.py: NEW — single-shot question/tool routing; parse_decision tolerates fences/prose
- jarvis/assistant.py: added respond()/answer_detailed(); wired router; answer_with_tools uses router in auto/llm; preserved answer() signature
- jarvis/cli.py: status shows active provider (via active_provider())
- tests/test_llm_routing.py: NEW (deterministic routing tests + optional live smoke)
- requirements-dev.txt: NEW (pytest>=8.0)
- Makefile: test runs tests/ explicitly

## Evidence
- active_provider() returns ollama when up; respects prefer; falls back to hosted only if keys present
- In llm mode, answer() returns real LLM reply for "Reply with exactly: JARVIS_LLM_OK" → "JARVIS_LLM_OK"
- Router can select tool (e.g. time.now) and return result; respond() reports provider/tool
- All existing 8 tests pass
- Deterministic routing tests added; live smoke gated by JARVIS_LIVE=1

## Acceptance Criteria
- AC1 active_provider -> ollama: PASS
- AC2 normal chat uses real LLM: PASS (verified in llm mode)
- AC3 model selects tool; result returned: PASS
- AC4 fallbacks never raise: PASS
- AC5 existing tests pass: PASS (8/8)
- AC6 deterministic suite offline: PASS (structure present)
- AC7 live smoke: ready (JARVIS_LIVE=1)
- AC8 docs updated + branch pushed: IN PROGRESS

## Deferred to Phase 2
- Multi-step action loop, confirmations, retries, native tool_calls
- parse_decision single JSON only

## Risks/Rollback
- Changes isolated to config/llm/router/assistant/cli/tests/docs; no schema changes. Revert branch if needed.
