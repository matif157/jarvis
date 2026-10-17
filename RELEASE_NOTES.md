# Release Notes — Jarvis v1.0.1

Released: 2026-10-17

Patch release fixing a routing/execution correctness bug and wiring up tools
that were present in the codebase but not exposed to the assistant.

## Fixes

- **Double execution**: the router used to run a tool *and* the action loop ran
  it again. The router now only decides; the action loop is the sole executor,
  so each tool runs exactly once.
- `task.reopen` / `task.cancel` no longer raise `NameError` (missing `datetime`).

## Added

- Registered `task.*`, `memory.*`, and `web.search` / `web.research` tools
  (registry: 69 → **80** tools).
- Interactive confirmation before destructive tools in `jarvis chat`/`start`;
  non-interactive runs report `confirmation required` instead of executing.
- Permission scopes `web.research`, `note.*`, `task.*`, `memory.*`.

## Verification

- **317 automated tests across 30 modules** (dependency-free runner and pytest).

---

# Release Notes — Jarvis v1.0.0

Released: 2026-10-17

Jarvis v1.0.0 is the first stable release: a local-first macOS personal AI
assistant that can chat, use tools, manage memory/tasks/notes, act on the
system, research the web, and coordinate higher-level workflows — all with
explicit confirmation for consequential actions.

## Highlights

- **Local-first chat & routing** across multi-provider AI (Groq, Gemini,
  OpenRouter, Ollama) with an offline "basic" fallback and an optional
  Atif Assistant bridge.
- **A single, reliable action loop** with tool selection, multi-step execution,
  and permission gating.
- **Productivity**: tasks, notes, and trusted memory with context injection.
- **Safe macOS actions**: open apps/URLs, reveal files, create files — with
  path/scheme safety checks.
- **Web search & research** with source-linked reports and an offline mock.
- **Google Drive**, **resume/career**, and **email** integrations (opt-in,
  credential-gated).
- **Job discovery & application workflow** with a status state machine and
  offline cover-letter drafting.
- **Voice I/O**: macOS `say` TTS plus optional/pluggable STT.
- **API + web UI**: JSON endpoints for every tool, chat, and status; a
  three-tab web console (Chat / Tools / Settings).
- **Resumable workflows**: persistent multi-step plans that survive restarts.
- **Atif bridge & optional IoT**: forward questions to an Atif Assistant and
  control registered smart devices (mock/HTTP/Home Assistant).

## Verification

- 289 automated tests across 29 modules (dependency-free runner and pytest).
- Every phase verified as `IMPLEMENTED` / `UNIT-TESTED`; Atif health
  additionally `INTEGRATION-TESTED` against a live instance.

## Install

```bash
git clone https://github.com/matif157/jarvis.git
cd jarvis
pip install -r requirements.txt
pip install -e .          # provides the `jarvis` command

python3 main.py status
python3 main.py chat
python3 main.py serve     # web UI at http://127.0.0.1:8771
```

## Compatibility

- Python 3.9 – 3.12
- macOS (full functionality); the core assistant runs on other platforms with
  reduced system-action support.

## Notes

- Optional integrations (Drive, email, cloud providers) require your own
  credentials and remain disabled until configured.
- No secrets are logged; local data lives under `data/` and `config/`.
