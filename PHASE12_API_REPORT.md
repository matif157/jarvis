# Phase 12 Report — API / Web UI

## Implemented
- **Extended API** (`jarvis/app.py`, version `0.2.0`): exposes the assistant's full tool surface and a chat endpoint, alongside the existing provider/settings API.

### Endpoints
| Endpoint | Method | Purpose |
|---|---|---|
| `/api/health` | GET | Health + provider probe; now accepts `?probe=false` to skip live probing |
| `/api/status` | GET | Offline snapshot: tool count, provider readiness, voice availability, host/port |
| `/api/tools` | GET | List all 51 registered tools (name, description, permissions) |
| `/api/tools/{name}` | POST | Execute a tool by name (`params`, `confirm`); unknown → 404 |
| `/api/chat` | POST | Chat returning `text`, `provider`, `tool`, `session`, `mode` |
| `/api/ask` | POST | Existing simple ask (kept for compatibility) |
| `/api/settings`, `/api/providers*` | GET/POST | Existing provider/key management (unchanged) |

### Tool execution semantics
- Body: `{"params": {...}, "confirm": false}`.
- Unknown tool → HTTP 404 with `{"success": false, "error": "unknown tool: ..."}`.
- Confirmation-gated permissions (e.g. `email.send`, `voice.listen`) return `success: false` with `meta.needs_confirmation = true` unless `confirm: true` is passed — never silently executed.

## Web UI (`web/`)
Rewrote the single-page UI into three tabs (vanilla JS, no build step, existing provider code preserved):
- **Chat** — message log with per-message provider attribution, mode selector (auto/basic/llm/atif), Enter-to-send.
- **Tools** — clickable list of every tool (description + permissions), JSON params editor, "confirm" checkbox for gated tools, pretty-printed JSON result viewer.
- **Settings** — existing provider/API-key cards and preferences (element IDs unchanged).

A status line in the header shows tool count, AI readiness, and TTS/STT availability.

## Safety
- Local-only bind by default (`127.0.0.1:8771`).
- Provider-prefixed settings keys are never returned by `GET /api/settings`.
- Confirmation gating enforced server-side (not just in the UI).
- No new dependencies.

## Acceptance Tests (12/12 Passed, fully offline)
Health probe opt-out (1); status snapshot (2); tool listing incl. phase tools + permissions (3); echo roundtrip (4); unknown-tool 404 (5); gated tool without confirm → `needs_confirmation` (6); gated tool with confirm passes the gate (7); chat basic mode offline (8); settings roundtrip blocking provider keys (9); providers endpoint structure (10); index page with Chat/Tools/Settings tabs (11); static JS/CSS served and include chat UI (12).

## All Tests Pass (240 tests across 27 modules)
