# CHANGELOG.md

All notable changes to this project are documented here. Dates use YYYY-MM-DD.

## 2026-10-17 (Phase 19 - On-device LLM & model download manager / v1.2.0)
- **New `jarvis/ondevice.py`**: model catalogue (Gemma 3 270M / Gemma 3 1B / Gemma 4 E2B `.litertlm` builds, exact byte sizes), a resumable-free download manager (`<data dir>/models`, streamed in 256 KB chunks with live progress/speed, free-space pre-check, `.part` staging, size verification, cancel) and the engine bridge (`is_ready`/`load`/`unload`/`chat`). Downloads authenticate with the `hf` service key when set. Gated repos produce an actionable message (set token + accept the Gemma licence on huggingface.co).
- **Chat routing on-device** (`jarvis/llm.py`): new `chat.llm=on_device` engine mode goes straight to the local model (`ProviderError` when none is loaded); `auto` prefers a configured cloud provider and falls back to the on-device engine when no key is set; `cloud` is unchanged. `active_provider()` reports `on_device`.
- **New endpoints** (`jarvis/app.py`): `GET /api/ondevice/info`, `GET /api/ondevice/models`, and `POST /api/ondevice/{download,cancel,delete,load,unload,generate}` — exact error codes for unknown model (404), already installed / not downloaded / no download in progress / not enough space (409).
- **Settings UI**: **On-device model** section — per-model cards with size/RAM hints, live download progress bar, cancel/delete/load/unload buttons, and a checklist entry showing when offline chat is ready.
- **Android bridge** (`ai.jarvis.assistant.llm.OnDeviceLlm`, Java): LiteRT-LM `com.google.ai.edge.litertlm:litertlm-android:0.18.0` (CPU backend), serialised load/unload/generate, JSON in/out so Python stays stateless; `deviceInfo()` reports RAM and ABIs from `/proc/meminfo`.
- **APK**: now arm64-v8a only (LiteRT-LM native libs double the size; Apple-Silicon emulators and the target phone are arm64). Building the app now requires **JDK 21** (the AAR ships Java 21 class files).
- Added `tests/test_phase19_ondevice.py` (8 offline checks: catalogue sanity, streamed install/verify/delete, cancel cleanup, gated-token error, endpoint behaviour, bridge wiring into `llm.complete`, honest failure without a model, UI assets).
- Full regression suite passes (**357 tests across 35 modules**).

## 2026-10-17 (Phase 18 - Guided key setup & engine manager / v1.1.0)
- **New `jarvis/service_keys.py`**: local storage for non-LLM service tokens (`hf`, `picovoice`) under `secret.<name>` in the settings table — masked (`…abcd`) in every payload, raw value never returned by any endpoint.
- **New `jarvis/engines.py`**: validated engine selection per component (`llm`: auto/cloud/on_device, `stt`: on_device/cloud/auto, `image`: local/cloud/off), persisted under `engine.<name>`; invalid values are rejected before reaching the DB. Consumers land with their phases (on-device LLM, mobile voice, local image service).
- **New endpoints**: `GET /api/keys` + `POST /api/keys/{name}` (save/clear service keys, 404 on unknown) and `GET /api/engines` + `POST /api/engines` (partial updates; invalid choice → 400).
- **Hardened `/api/settings`**: both read and write now skip `provider.*`, `secret.*` and `engine.*` prefixes, closing the gap where generic settings writes could have stored a secret (previously only `provider.*` was filtered on read).
- **Settings UI**: guided **Setup status** checklist (chat provider / HF token / Picovoice key / engine choices, clickable to jump to the fix), **Service API keys** cards, and **Engine selection** dropdowns — all persisted via the new endpoints.
- Added `tests/test_phase18_settings_engine.py` (6 offline checks incl. leak-proofing of `secret.*`/`engine.*`).
- Full regression suite passes (**349 tests across 34 modules**).

## 2026-10-17 (Phase 17 - Transparent Agent Console / live timeline)
- **New event bus** `jarvis/events.py`: dependency-free, sync-or-async `EventEmitter` that never lets instrumentation break the actual work (handler errors are swallowed). Event types: `start`, `thought`, `confirmation`, `tool_call`, `tool_result`, `message`, `error`, `done`.
- **Action loop instrumentation** (`jarvis/action_loop.py`): emits `thought` → `confirmation` (when gated) → `tool_call` → `tool_result` (with `duration_ms` and `needs_confirmation`) for every tool step. Behaviour is unchanged when no handler is attached.
- **Assistant streaming** (`jarvis/assistant.py`): `Assistant.respond(query, on_event=None)` now emits `start` and the final `message` (with provider/tool). Fully backward compatible.
- **SSE endpoint** `GET /api/agent/stream` (`jarvis/app.py`): streams the timeline as Server-Sent Events for `EventSource` clients. No new dependency (uses `StreamingResponse`); runs the assistant in a background task and terminates with a `done` event. The legacy `POST /api/chat` is untouched.
- **Web UI** (`web/`): new **Agent** console tab — a live, colour-coded timeline (routing, tool calls, args, results, timing) — fed by the same stream as the **Chat** tab, whose replies now carry a collapsible per-turn step trace. Falling back to `POST /api/chat` if the stream cannot open.
- Added `tests/test_phase17_agent_stream.py` (10 offline checks: emitter semantics, action-loop events, assistant events, SSE frames, backward compat, UI assets).
- Full regression suite passes (**343 tests across 33 modules**).

## 2026-10-17 (Phase 16 - Missing-tool wiring & routing correctness / v1.0.1)
- **Fixed a double-execution bug**: `Router.route` no longer executes tools (it only decides chat vs. tool). `ActionLoop` is now the single executor, so every chosen tool runs exactly once.
- **Wired missing tools** into `get_enhanced_registry()`:
  - `task.add` / `task.list` / `task.complete` / `task.reopen` / `task.cancel` (5)
  - `memory.remember` / `memory.recall` / `memory.list` / `memory.forget` (4)
  - `web.search` / `web.research` (new `get_web_tools()` in `jarvis/web_search.py`, offline mock)
  - Registry grows from 69 → **80** tools.
- **Fixed `NameError`** in `TaskReopenTool` / `TaskCancelTool` (missing `datetime` import).
- **Corrected macOS action class names** during re-registration (`OpenAppTool`, `OpenURLTool`, `RevealInFinderTool`, `CreateFileTool`).
- **Confirmation gating**: interactive chat (`jarvis chat`/`start`) now prompts before running destructive tools; non-interactive runs return an honest `confirmation required` result instead of silently executing.
- **Removed duplicated routing logic** in `Assistant.respond` (dead second router pass).
- **Permissions allowlist** extended with `web.research`, `note.read/write`, `task.read/write`, `memory.read/write`.
- Refreshed the assistant system prompt (removed the stale hard-coded tool list).
- Added `tests/test_phase16_tools_and_routing.py` (11 offline checks incl. exactly-once execution and confirmation gating).
- Full regression suite passes (**317 tests across 30 modules**).
- Post-release hardening: hardened `Assistant.start()` (session now runs under `asyncio.run`, so the event loop is created/closed properly; behavior unchanged) with a regression test; exercised the API server + web UI end-to-end (`/api/health`, `/api/tools`, `/api/chat`, `/`, tool execution) and documented it; added a README "Architecture & naming" section clarifying `tasks.TaskManager` vs `engine_tasks.TaskExecutor`, `memory.Memory` vs `memory_enhanced.EnhancedMemory`, and the router/action-loop/engine layering. Suite now **318 tests**.
- Security: `PermissionManager.is_allowed(scope, resource=None)` now **enforces allowlist patterns** when a resource (e.g. a path) is supplied (home-relative globs, `~/*`, wildcards); scope-only calls stay backward compatible. Resource enforcement is wired into resource-bearing tools through the new `Tool.resource_kwarg` (`fs.list`/`fs.read`, `finder.reveal`, `file.create`). Completed the default allowlist (added `email.connect/read`, `drive.access/read`, `resume.*`, `career.*`) and aligned `config/permissions.json`. Added `tests/test_permissions_allowlist.py` (9 checks). Suite now **327 tests across 31 modules**.

## 2026-10-17 (Phase 15 - Release Readiness / v1.0.0)
- Promoted the project to its first stable release: **v1.0.0** (bumped in `jarvis/__init__.py` and `setup.py`; the API now reports the package version instead of a hardcoded string).
- Packaging: expanded `setup.py` (license, classifiers, `extras_require[dev]`, `project_urls`, `zip_safe=False`, version floors); added `pyproject.toml` (`[build-system]` + pytest/ruff config); added `MANIFEST.in` so the sdist ships the web UI, docs, and scripts while pruning `data/`.
- Licensing: added `LICENSE` (MIT, © 2026 Muhammad Atif).
- Docs: rewrote `README.md` (features, requirements, install, quickstart, usage, configuration table, security, testing, structure); added `RELEASE_NOTES.md` (v1.0.0) and `RELEASING.md` (release checklist).
- Tooling: added dependency-free `scripts/run_tests.py` runner; reworked `Makefile` (`install`, `install-dev`, `test`, `test-pytest`, `lint`, `build`/`dist`, `serve`, `clean`).
- CI: added `.github/workflows/ci.yml` running the suite + byte-compile across Python 3.9–3.12.
- Config: `jarvis/config.py` now loads an optional `.env` via `python-dotenv`; added `.env.example` documenting all variables.
- Cleanup: removed the stray `test_file.txt`; made `tests/test_basic.py::test_version` version-agnostic.
- Added `tests/test_phase15_release.py` (17 offline checks: version consistency, artifacts, packaging, CI, docs).
- Full regression suite passes (306 tests across 29 modules; 69 tools).

## 2026-10-17 (Phase 14 - Atif Bridge / IoT)
- Atif bridge promoted to first-class tools (`jarvis/atif_client.py`), using synchronous HTTP so tools work inside the async action loop:
  - `atif.status` — bridge URL, reachability, active answer mode
  - `atif.ask` — forward a question to a running Atif Assistant (payload matches its `Ask` schema)
  - `atif.set_url` — configure the bridge URL (http/https validated)
  - Verified live: health against a running Atif Assistant on `127.0.0.1:8770` returned real provider/memory data
- Added optional IoT layer (`jarvis/iot.py`), local-first and honest:
  - `Device` + `DeviceStore` (JSON under `data/iot/devices.json`); CRUD + persisted state
  - Pluggable providers: `MockDeviceProvider` (offline), `HttpDeviceProvider` (generic REST, http(s)-only), `HomeAssistantProvider` (used only when URL+token are configured)
  - `IoTManager` resolves providers and executes on/off/toggle/set/status
- 6 registered IoT tools: `iot.providers`, `iot.devices`, `iot.add_device`, `iot.remove_device`, `iot.status`, `iot.control`
- Permissions: `atif.read/ask/config`, `iot.read/write` allowed; `iot.control` confirmation-gated (destructive). No device is contacted unless registered and explicitly controlled.
- CLI: added `jarvis iot providers|list|add|control|remove` (Atif already has `jarvis atif ...`)
- Added `tests/test_phase14_atif_iot.py` with 22 offline acceptance tests (network helpers patched; temp IoT store)
- All 22 Phase 14 tests pass; full regression suite passes (289 tests across 29 modules; 69 tools total)

## 2026-10-17 (Phase 13 - Resumable Workflows)
- Added `jarvis/workflows.py`: persistent, resumable multi-step workflows:
  - `Workflow` / `WorkflowStep` dataclasses; statuses `pending/running/paused/blocked/completed/failed/cancelled`
  - `WorkflowStore`: one JSON file per workflow under `data/workflows/`, atomic writes; supports list/status/tag filters and delete
  - `WorkflowEngine`: `create`, `from_goal` (via Planner), `start`, `resume`, `pause`, `cancel`, `delete`
  - State is saved after every step, so workflows survive process restarts and resume from the next incomplete step
  - Per-step `max_retries`, `optional`, and `continue_on_error`; attempts recorded
  - Argument interpolation: `${goal}`, `${context.<key>}`, `${steps.<id>.result[.<path>]}`, `${steps.<id>.status}`
  - Confirmation-required steps set the workflow to `blocked` (resumable) instead of running; `resume` authorizes the remaining steps
- 9 registered tools: `workflow.create`, `workflow.from_goal`, `workflow.list`, `workflow.get`, `workflow.start`, `workflow.resume`, `workflow.pause`, `workflow.cancel`, `workflow.delete`
- Permissions: `workflow.read` / `workflow.write` allowed; `workflow.run` confirmation-gated (destructive)
- CLI: added `jarvis workflow list|show|create|run|resume|cancel`; fixed a misplaced `if __name__ == "__main__"` block so `python -m jarvis.cli` registers all commands
- Added `tests/test_phase13_workflows.py` with 27 offline acceptance tests (temp store; no network)
- All 27 Phase 13 tests pass; full regression suite passes (267 tests across 28 modules)
- Fixed an infinite-loop bug: a `continue_on_error` failed step is now considered handled by `next_step`

## 2026-10-17 (Phase 12 - API / Web UI)
- Extended the FastAPI app (`jarvis/app.py`) to expose the assistant's full capability set:
  - `GET /api/tools` — list all 51 registered tools with description + permissions
  - `POST /api/tools/{name}` — execute a tool by name (`params`, `confirm`); unknown tools return 404
  - `POST /api/chat` — chat with provider/tool attribution (`text`, `provider`, `tool`, `session`, `mode`)
  - `GET /api/status` — offline snapshot: tool count, provider readiness, voice availability, host/port
  - `GET /api/health` — now accepts `probe=false` to skip live provider probing
- Confirmation-gated tools (e.g. `email.send`, `voice.listen`) are surfaced honestly over HTTP as `needs_confirmation` unless `confirm: true`
- Upgraded the web UI (`web/index.html`, `web/app.js`, `web/style.css`) to three tabs:
  - Chat (message log with provider attribution, mode selector)
  - Tools (searchable tool list, JSON params editor, confirm checkbox, JSON result viewer)
  - Settings (existing provider/key management, unchanged IDs)
- Added `tests/test_phase12_api.py` with 12 offline acceptance tests (FastAPI TestClient; no network)
- All 12 Phase 12 tests pass; full regression suite passes (240 tests across 27 modules)

## 2026-10-17 (Phase 11 - Voice)
- Implemented voice I/O module (`jarvis/voice.py`), local-first and honest about availability:
  - Text-to-speech: `MacSayTTS` (macOS `say` command) + `MockTTS` for tests
  - Speech-to-text: pluggable `WhisperSTT` / `SpeechRecognitionSTT` (used only when installed) + `MockSTT`
  - `VoiceManager`: coordinates TTS/STT with graceful fallback and availability status
- 5 registered tools: `voice.status`, `voice.speak`, `voice.listen`, `voice.transcribe`, `voice.voices`
- Consent & safety:
  - Microphone/listening is confirmation-gated (`voice.listen`); speaking is allowed (`voice.speak`)
  - Audio paths validated with `is_path_safe`; no fake transcripts — missing backend/file returns an honest error
  - No new dependencies (uses the system `say` command; STT backends are optional)
- Added `tests/test_phase11_voice.py` with 28 offline acceptance tests (no audio playback, no microphone)
- All 28 Phase 11 tests pass; all existing regression modules pass (26 modules total)
- Updated docs: `PHASE_COMPLETION_MATRIX.md`, `PROJECT_STATUS.md`, `TASKS.md`, `CHANGELOG.md`

## 2026-10-17 (Phase 10 - Job Discovery / Application Workflow)
- Implemented job discovery and application workflow module (`jarvis/jobs.py`):
  - `JobListing`, `JobSearchQuery`, `JobApplication` dataclasses; `APPLICATION_STATUSES` + `ALLOWED_TRANSITIONS` state machine
  - Pluggable discovery: `JobSource` ABC, `MockJobSource` (offline/deterministic), `WebSearchJobSource` (reuses Phase 6 search), `JobSearchManager` with graceful fallback
  - `JobMatcher`: scores listings against career profile / resume skills, target roles, remote
  - `JobStore` and `ApplicationStore`: JSON persistence under `data/jobs/`
  - `CoverLetterGenerator` (offline template + optional enhancer hook) and `ApplicationChecklist`
- 13 registered tools: `job.search`, `job.list`, `job.get`, `job.save`, `job.match`, `application.add`, `application.list`, `application.get`, `application.update_status`, `application.delete`, `application.prepare`, `application.followup`, `job.stats`
- Consent & safety:
  - Follow-up email default is draft-only (`send=False`); `send=True` sends only when an account is connected and an explicit recipient is given
  - Permission scopes `job.read`, `job.write` (allow) and `job.apply` (confirmation-gated) added to the model
  - No false success: missing listings/applications/accounts return honest errors
- Added `tests/test_phase10_jobs.py` with 42 offline acceptance tests
- All 42 Phase 10 tests pass; all existing regression modules pass (25 modules total)
- Updated docs: `PHASE_COMPLETION_MATRIX.md`, `PROJECT_STATUS.md`, `TASKS.md`, `CHANGELOG.md`

## 2026-10-15 (Phase 9 - Email/Messaging with Consent)
- Implemented email/messaging module (`jarvis/email.py`) with secure IMAP/SMTP integration:
  - `EmailAccountManager`: Multi-account management with OAuth 2.0 flow
  - `EmailClient`: IMAP/SMTP client with SSL/TLS support
  - 7 registered tools: `email.connect`, `email.disconnect`, `email.status`, `email.search`, `email.read`, `email.send`, `email.list_folders`
- Security features:
  - OAuth 2.0 flow with local server (port 8080)
  - Read/write/send permissions with existing permission model
  - Credentials stored with 0600 permissions
  - Multiple provider support (Gmail, Outlook, Yahoo, iCloud, Fastmail, ProtonMail)
  - URL safety validation for links in emails
  - Credentials never logged or exposed
- Supported operations:
  - Account connect/disconnect/status
  - Search emails by query, folder, date range
  - Read emails with full parsing (headers, body, attachments)
  - Send emails with text/HTML, CC/BCC, attachments
  - List folders/labels
  - Multiple provider support (Gmail, Outlook, Yahoo, iCloud, Fastmail, ProtonMail)
- Added `tests/test_phase9_email.py` with 30 acceptance tests
- All 30 Phase 9 acceptance tests pass
- All existing regression tests pass (24 test modules, 100+ tests)
- Updated documentation: `PHASE_COMPLETION_MATRIX.md`, `PROJECT_STATUS.md`, `TASKS.md`


## 2026-10-15 (Phase 8 - Resume/Career Integration)
- Implemented resume and career management module (`jarvis/career.py`):
  - `ResumeParser`: Parses resume text into structured data (contact, sections, skills, experience, education, projects)
  - `ResumeStore`: JSON-based persistence with CRUD operations
  - `CareerProfileStore`: Manages career profile with skills, target roles, notes, resume links
  - 6 registered tools: `resume.parse`, `resume.list`, `resume.get`, `resume.delete`, `career.profile`, `resume.search`
- Features:
  - Resume parsing: contact extraction, section detection, skill keyword extraction (100+ keywords)
  - Section detection: summary, experience, education, skills, projects, certifications, languages, awards, publications
  - Skill extraction: 100+ tech keywords, case-insensitive matching
  - Resume storage: JSON persistence with CRUD operations
  - Career profile: skills, target roles, notes, linked resumes
  - Resume search: keyword search across skills, experience, content
  - Career profile tool: view, add target role, add skill, add note
  - Resume search tool: keyword search with relevance scoring
- Registered 6 tools in enhanced registry
- Added `tests/test_phase8_career.py` with 16 acceptance tests
- All 16 Phase 8 acceptance tests pass
- All existing regression tests pass (22 test modules, 100+ tests)
- Updated documentation: `PHASE_COMPLETION_MATRIX.md`, `PROJECT_STATUS.md`, `TASKS.md`


## 2026-10-15 (Phase 7 - Google Drive Integration)
- Implemented Google Drive integration (`jarvis/google_drive.py`) with secure OAuth 2.0 flow:
  - `GoogleDriveAuth`: OAuth 2.0 flow with local server, token storage with 0600 permissions
  - `GoogleDriveService`: API wrapper for search, metadata, content retrieval, folder listing
  - 7 registered tools: `drive.connect`, `drive.disconnect`, `drive.status`, `drive.search`, `drive.get_file`, `drive.read`, `drive.list_folder`
- Security features:
  - Read-only OAuth scope (`drive.readonly`)
  - Application allowlist not needed (user grants consent via Google)
  - Token stored with 0600 permissions in data directory
  - Token refresh on expiry
  - Path validation against approved directories
  - MIME type allowlist for supported formats
  - File size limits (100KB default) for content extraction
  - No write/modify/delete operations
- Registered 7 tools in enhanced registry: `drive.connect`, `drive.disconnect`, `drive.status`, `drive.search`, `drive.get_file`, `drive.read`, `drive.list_folder`
- Added `tests/test_phase7_google_drive.py` with 20 acceptance tests
- All 20 Phase 7 acceptance tests pass
- All existing regression tests pass (21 test modules, 100+ tests)
- Updated documentation: `PHASE_COMPLETION_MATRIX.md`, `PROJECT_STATUS.md`, `TASKS.md`
- OAuth 2.0 flow uses local server on port 8080, requires `google_client_secrets.json`
- Supported MIME types: Google Docs, Sheets, Slides, PDF, DOCX, XLSX, PPTX, plain text
- Content extraction with 100KB size limit
- Permission model: `drive.read` for search/read/list, `drive.access` for connect/disconnect


## 2026-10-15 (Phase 6 - Web Research and Source Verification)
- Implemented web research module (`jarvis/web_search.py`) with complete research pipeline:
  - Search provider abstraction (`SearchProvider` ABC) with mock and extensible real providers
  - `MockSearchProvider` for deterministic testing (no network calls)
  - `SearchManager` for multi-provider orchestration and fallback
  - `ResearchPipeline` end-to-end: query → sub-queries → search → fetch → evidence → report
  - URL safety validation (blocks localhost, private IPs, metadata endpoints)
  - HTML text extraction with script/style stripping
  - URL safety validation (blocks localhost, private IPs, metadata endpoints, unsafe schemes)
  - Evidence extraction with keyword overlap scoring
  - Markdown report generation with citations, sources, limitations
  - `research()` convenience function for easy integration
- Added `MockSearchProvider` for deterministic testing (no network calls)
- Added `SearchManager` for multi-provider orchestration with fallback
- Added 20 acceptance tests in `tests/test_phase6_web_research.py`
- Updated documentation: `PHASE_COMPLETION_MATRIX.md`, `PROJECT_STATUS.md`, `TASKS.md`
- All 20 Phase 6 acceptance tests pass
- All existing regression tests pass (20 test modules, 100+ tests)
- No breaking changes to existing functionality


## 2026-10-15 (Phase 5 - Safe macOS Actions)
- Implemented macOS actions adapter (`jarvis/macos_actions.py`) with 4 restricted, safe operations:
  - `app.open`: Open approved macOS applications via osascript (Safari, Chrome, Firefox, Terminal, Finder, Notes, Messages)
  - `url.open`: Open valid HTTP/HTTPS URLs with strict scheme validation
  - `finder.reveal`: Reveal files in Finder with path safety validation
  - `file.create`: Create files in approved directories with path traversal protection and no silent overwrite
- Added comprehensive security: application allowlist, URL scheme validation (HTTP/HTTPS only), path validation against approved directories, path traversal protection, no silent overwrites
- Registered 4 new tools in `get_enhanced_registry()`: `app.open`, `url.open`, `finder.reveal`, `file.create`
- Added `tests/test_phase5_macos_actions.py` with 15 acceptance tests covering all required journeys
- Updated documentation: PHASE_COMPLETION_MATRIX.md, PROJECT_STATUS.md, TASKS.md
- All 15 Phase 5 journeys pass; all existing regression tests pass (19 test modules)
- No breaking changes to existing functionality

## 2026-10-13 (Audit)
- Created PROJECT_STATUS.md with comprehensive audit (phases 1-8, feature matrix, test results, verified vs unverified, known issues).
- Verified existing tests pass (8/8). Ran manual checks: basic chat, note creation, task creation, memory persistence, weather (mock), CLI status.
- Inspected architecture: modules, DB schema, security, tools, agent/planner, API/web UI, migration. No code changes.
- Identified unverified live integrations (LLM/Atif/API server runtime) vs offline functionality.
- Established baseline for tracking remaining work in TASKS.md.

## 2026-10-13 (Phases 1-8 implementation - prior)
- Phase 1-8 completed: foundation, conversation, tools, memory enhanced, autonomy, security, migration safety, polish (engine). All tests pass.

## 2026-10-13 (Phase 1: Verify Real AI Connectivity)
- Inspected provider configuration (groq/gemini/openrouter/ollama). Groq key returns 401; ollama local model misconfigured (llama3.2 not found).
- Fixed minimal: set ollama default model to llama3.2:1b (matching installed model).
- Live test with "Reply with exactly: JARVIS_LLM_OK" succeeded via complete() returning response from ollama (real model). Direct ollama API call confirmed.
- Updated PROVIDER_TEST_RESULTS.md. All existing tests still pass (8/8).

## 2026-10-14 (Phase 4 - Memory Control)
- Implemented controllable memory system with remember/retrieve/forget/list operations
- Added MemoryRememberTool, MemoryRecallTool, MemoryListTool, MemoryForgetTool
- Integrated memory context injection into assistant._get_context_memories
- Added FindFilesTool for safe file discovery
- Added Phase 4 acceptance tests (10 user journeys)
- All 10 user journeys verified end-to-end
- Updated PHASE_COMPLETION_MATRIX.md, PROJECT_STATUS.md, TASKS.md
- No breaking changes to existing functionality