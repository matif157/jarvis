# TASKS.md — Prioritized Remaining Work

Status keys: NOT STARTED | IN PROGRESS | IMPLEMENTED | TESTED | VERIFIED WORKING | BLOCKED | FAILED

## High priority (verification/integration)
- [x] **Verify live LLM connectivity** (status: VERIFIED WORKING) — Tested with ollama (llama3.2:1b). complete() returned exact expected response "JARVIS_LLM_OK". Evidence in PROVIDER_TEST_RESULTS.md.
- [ ] **Verify Atif integration live** (status: NOT STARTED) — Dependencies: Atif running on http://127.0.0.1:8770 (optional). Acceptance: health check returns ok=true or documented unreachable; one ask() roundtrip if ok. Safe-only.
- [ ] **Exercise API server + web UI** (status: NOT STARTED) — Dependencies: none. Acceptance: start server briefly, hit /api/health, load web/index.html; stop cleanly. No external calls.

## Medium priority (robustness/docs)
- [ ] **Add pytest runner / test instructions** (status: NOT STARTED) — Dependencies: none. Note: tests run fine via direct python; adding pytest optional. Acceptance: `pytest -v` works or documented alternative.
- [ ] **Harden assistant.start() event loop** (status: NOT STARTED) — Dependencies: none. Small refactor (asyncio.run pattern) without changing behavior. Acceptance: existing chat tests still pass; manual chat works.
- [ ] **Document class naming/API surface** (status: NOT STARTED) — Dependencies: none. Acceptance: README or docs clarify TaskManager vs Tasks, memory vs memory_enhanced, etc.

## Low priority (enhancements)
- [ ] **Weather: real API** (status: NOT STARTED) — Dependencies: optional API key/provider. Acceptance: configurable provider with safe fallback to mock; no breaking changes.
- [ ] **Planner sophistication** (status: NOT STARTED) — Dependencies: none. Acceptance: better decomposition without over-engineering; preserve backward compat.
