# TASKS.md — Prioritized Remaining Work

Status keys: NOT STARTED | IN PROGRESS | IMPLEMENTED | TESTED | VERIFIED WORKING | BLOCKED | FAILED

## High priority (verification/integration)
- [x] **Verify live LLM connectivity** (status: VERIFIED WORKING) — Tested with ollama (llama3.2:1b). complete() returned exact expected response "JARVIS_LLM_OK". Evidence in PROVIDER_TEST_RESULTS.md.
- [x] **Verify Atif integration live** (status: VERIFIED WORKING for health) — Bridge installed as `jarvis atif status|chat|url`; health verified live against a running Atif Assistant on http://127.0.0.1:8770. `atif.ask` roundtrip not user-flow-verified (live ask exceeded the sync timeout), so ask remains unit-tested only.
- [ ] **Exercise API server + web UI** (status: NOT STARTED) — Dependencies: none. Acceptance: start server briefly, hit /api/health, load web/index.html; stop cleanly. No external calls.

## Medium priority (robustness/docs)
- [x] **Add pytest runner / test instructions** (status: VERIFIED WORKING) — Phase 15 added a dependency-free `scripts/run_tests.py` runner (`make test`), documented testing in README, and a GitHub Actions CI matrix. `make test-pytest` uses pytest when installed.
- [ ] **Harden assistant.start() event loop** (status: NOT STARTED) — Dependencies: none. Small refactor (asyncio.run pattern) without changing behavior. Acceptance: existing chat tests still pass; manual chat works.
- [ ] **Document class naming/API surface** (status: NOT STARTED) — Dependencies: none. Acceptance: README or docs clarify TaskManager vs Tasks, memory vs memory_enhanced, etc.

## Low priority (enhancements)
- [ ] **Weather: real API** (status: NOT STARTED) — Dependencies: optional API key/provider. Acceptance: configurable provider with safe fallback to mock; no breaking changes.
- [ ] **Planner sophistication** (status: NOT STARTED) — Dependencies: none. Acceptance: better decomposition without over-engineering; preserve backward compat.

# Phase 4 Memory Control: All 10 user journeys verified - save, retrieve, correct, delete, export, edge cases

# Phase 5 macOS Actions: All 15 user journeys verified - app.open, url.open, finder.reveal, file.create all functional


# Phase 6 Web Research: All 20 acceptance tests verified - search providers, research pipeline, source retrieval, report generation, security


# Phase 7 Google Drive Integration: All 20 acceptance tests verified - OAuth flow, Drive search, file retrieval, file listing, permissions, read-only enforcement


# Phase 8 Resume/Career: All 16 acceptance tests verified - resume parsing, storage, search, career profile, skill extraction, section parsing


# Phase 9 Email/Messaging: All 30 acceptance tests verified - IMAP/SMTP client, OAuth flow, search/read/send, folder listing, permissions, security


# Phase 10 Job Discovery/Application Workflow: All 42 acceptance tests verified - pluggable discovery (mock/web search), matching, listing + application stores, status state machine, cover letter/checklist prep, follow-up email draft/send, job.stats


# Phase 11 Voice: All 28 acceptance tests verified - macOS say TTS, pluggable/optional STT (whisper/speech_recognition), mock providers, VoiceManager, voice.status/speak/listen/transcribe/voices tools, permission gating, honest fallback


# Phase 12 API/Web UI: All 12 acceptance tests verified - tool listing/execution API, status + chat endpoints, confirmation gating over HTTP, health probe opt-out, Chat + Tools + Settings web UI


# Phase 13 Resumable Workflows: All 27 acceptance tests verified - persistent workflow store, start/pause/resume/cancel lifecycle, resume after restart, confirmation checkpoints, ${} result interpolation, retries/optional/continue-on-error, 9 workflow tools, CLI group


# Phase 14 Atif Bridge/IoT: All 22 acceptance tests verified - atif.status/ask/set_url bridge tools (health live-verified), optional IoT registry with mock/http/home_assistant providers, address validation, confirmation-gated control, 6 iot tools, CLI group


# Phase 15 Release Readiness: All 17 acceptance tests verified - v1.0.0 unified across package/setup/API, pyproject.toml + MANIFEST.in packaging, MIT LICENSE, rewritten README, RELEASE_NOTES + RELEASING docs, dependency-free run_tests.py, reworked Makefile, GitHub Actions CI (3.9-3.12), optional .env loading; full suite 306 tests across 29 modules
