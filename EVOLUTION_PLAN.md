# Jarvis Evolution Plan: Integrate Atif Assistant Capabilities

## Overview

Currently Jarvis is a basic CLI assistant with notes, tasks, memory, weather, and simple chat. Atif Assistant (in ~/Projects/atif-assistant) is a sophisticated personal intelligence system with persistent memory (SQLite), API key management with settings UI, provider abstraction (Groq/Gemini/OpenRouter/Ollama), web UI, routing/engine for responses, file uploads, pattern radar, contradiction detection, etc. The user wants to evolve Jarvis to connect with Atif Assistant and add API key management/settings system.

## Goals
- Connect Jarvis with Atif Assistant (share functionality, perhaps run as client or integrate backend)
- Add API key management system with customizable settings UI
- Make Jarvis more sophisticated like Atif Assistant while keeping it usable
- Maintain local-first nature where possible

## Current State Comparison

### Jarvis (current)
- CLI-based (click/rich)
- JSON file storage (notes.json, tasks.json, memory.json)
- Basic chat with simple keyword matching
- Weather mock
- Basic CLI commands
- Python package structure

### Atif Assistant (target reference)
- FastAPI backend + web UI (HTML/JS/CSS)
- SQLite database with rich schema (facts, notes, messages, settings, providers, etc.)
- Multi-provider LLM support with runtime API key management
- Settings UI for providers, models, API keys (test keys before saving, masked hints)
- /api/settings and /api/providers endpoints
- Engine with routing, context building, instructions
- Memory system with search, contradictions detection
- File uploads, voice, speech, etc.
- Pattern radar, contradictions

## Plan to Evolve Jarvis

### Phase 1: Add Settings & API Key Management System
Mirror Atif's settings pattern in Jarvis.

**Backend changes:**
- Add SQLite storage (jarvis/db.py) for settings, providers, API keys
- API key storage with database override (env vars still work as fallback)
- Add settings CRUD operations (get_setting, set_setting, delete_setting)
- Add provider management (like Atif's provider_status, provider_key, provider_enabled)
- Mask API keys in responses (show only last 4 chars)

**CLI changes:**
- Add `jarvis settings` command to manage API keys/providers
- Add `jarvis config` to view/set config
- Store provider keys in DB, override env when set

### Phase 2: Multi-provider LLM Integration
Add LLM support similar to Atif's llm.py.

**Implementation:**
- Create jarvis/llm.py with provider support (groq, gemini, openrouter, ollama)
- Add provider abstraction with handlers, test functionality
- Integrate with chat - when API keys configured, use LLM; fallback to basic
- Add provider order/priority, enable/disable per provider
- Add test provider functionality

### Phase 3: Connect to Atif Assistant
The user wants Jarvis "connected with atif assistant" - interpret as:
- Option A: Make Jarvis a client to Atif Assistant API (call http://127.0.0.1:8770/api/ask)
- Option B: Embed/share functionality - allow Jarvis to talk to Atif's engine
- Option C: Merge capabilities - bring Atif's intelligence into Jarvis

Better approach: Add Atif-style API server mode to Jarvis so it can run as both CLI and API service. Also add client mode to connect to existing Atif instance.

**Add API server to Jarvis:**
- FastAPI app (jarvis/server.py or app.py) with endpoints: /api/ask, /api/settings, /api/providers, /api/health
- Serve simple web UI or API for programmatic access
- Can run alongside or instead of CLI

**Add client mode:**
- `jarvis connect --url http://127.0.0.1:8770` to use remote Atif instance
- Or detect if Atif is running and offer to use it

### Phase 4: Enhanced Intelligence (Atif-style Engine)
Bring key intelligence features.

**Features to add:**
- Router for question classification (ANSWERED/CHALLENGED/DECIDED)
- Context building with memory retrieval
- Better system prompts/instructions
- Pattern recognition/radar basics
- Contradiction detection in memory
- Memory extraction from conversations

### Phase 5: Web UI / Settings Interface
Add web UI for settings and chat (like Atif has).

**Implementation:**
- Add web/ directory with HTML/CSS/JS
- Settings page for API keys, providers, models
- Simple chat interface
- API endpoints to support UI

### Phase 6: Data Migration & Persistence
Improve from JSON to SQLite consistently.

- Migrate existing JSON data (notes/tasks/memory) to SQLite
- Keep backward compatibility or provide migration tool
- Unified data model

## Concrete Changes Needed

### New files in Jarvis:
- jarvis/db.py (SQLite schema, settings, providers)
- jarvis/llm.py (multi-provider LLM)
- jarvis/app.py or server.py (FastAPI API)
- jarvis/engine.py (response engine like Atif)
- jarvis/router.py (question routing)
- jarvis/config.py (extend existing)
- web/ (HTML/CSS/JS) for settings UI
- jarvis/migrate.py (JSON->SQLite migration)

### Modify existing files:
- jarvis/cli.py - add settings, config, serve commands
- jarvis/assistant.py - integrate LLM, connect to Atif if configured
- jarvis/core.py - use SQLite for notes
- jarvis/memory.py - use SQLite
- jarvis/tasks.py - use SQLite
- requirements.txt - add fastapi, httpx, uvicorn, sqlite-utils etc.
- README.md - document new capabilities

## API Key Management Design (as requested)
"create an api key system (i can customize this all in setting so avail all the optioin in setting)"

Following Atif's pattern:
- Settings stored in SQLite `settings` table (key, value, updated_at)
- Provider API keys stored as `provider.{name}.api_key` 
- Can set via UI or CLI: `jarvis settings set provider.groq.api_key sk-...`
- Keys masked in API responses (show …abcd)
- Test before save via `/api/providers/{name}/test`
- Can enable/disable providers, change models/URLs
- Settings page shows all options (providers, models, toggles, test buttons)

## Connection Strategy with Atif Assistant
Options:
1. Jarvis can act as client: add `--use-atif http://localhost:8770` to chat/note commands
2. Atif can be embedded? Or they share same backend
3. Create bridge: `jarvis atif connect` to link to running Atif instance
4. Add Atif-compatible API to Jarvis so they can interoperate

Recommend: Add both server mode to Jarvis (so it can be a full assistant API) and client mode to consume Atif API. This gives flexibility.

## Implementation Order (plan mode - just planning)
1. Analyze Atif's full implementation details (db schema, endpoints) - done partially
2. Design Jarvis DB schema for settings/providers
3. Implement settings + API key management
4. Add LLM provider abstraction
5. Add API server + web UI for settings
6. Enhance chat to use LLM
7. Add connection to Atif Assistant
8. Test and refine

## Questions to Clarify (but user wants plan; they gave direction)
The user said: "connect it with atif assistant and create an api key system (i can customize this all insetting so avail all the optioin in setting)"

So direction is clear - implement API key management system (like Atif's) with settings UI, and connect Jarvis to Atif Assistant.

## Next Steps
After user approves plan, implement in order. Keep changes incremental and testable.

## Detailed Implementation Steps

### 1. DB Schema for Jarvis
Create `jarvis/db.py` with SQLite schema mirroring Atif's patterns. Key tables:
- `settings(key, value, updated_at)` - for config and provider keys (api keys under `provider.*` prefix)
- `providers_state(name, enabled, model, url, updated_at)` - optional for provider state
- `notes(id, title, body, tags, created_at, updated_at)` - migrate from JSON
- `tasks(id, title, description, status, priority, created_at, updated_at)` - migrate from JSON
- `memory(id, key, value, updated_at)` - migrate from JSON
- `messages(session_id, role, content, labels, created_at)` - for conversation history
- Keep JSON as fallback during migration

Schema functions: `init_db()`, `connect()`, `set_setting()`, `get_setting()`, `delete_setting()`, CRUD for notes/tasks/memory.

### 2. Settings & API Key Management
- Add to `jarvis/db.py`: settings functions (mirror Atif's pattern)
- Add to `jarvis/llm.py`: provider abstraction (providers: groq, gemini, openrouter, ollama)
  - Functions: `provider_key()`, `provider_model()`, `provider_enabled()`, `provider_status()`, `mask_key()`, `_override()` (checks DB first, falls back to env)
  - Store keys as `provider.{name}.api_key`, models as `provider.{name}.model`, enabled as `provider.{name}.enabled`
- Add CLI commands in `jarvis/cli.py`:
  - `jarvis settings` - show current settings (masked)
  - `jarvis settings set <key> <value>` - set setting
  - `jarvis settings unset <key>` - clear setting
  - `jarvis providers` - list providers with status
  - `jarvis providers test [name]` - test providers
- API key masking: show last 4 chars like `…abcd`, never return full keys

### 3. LLM Integration
- Create `jarvis/llm.py` with handlers for each provider (similar to Atif)
- Chat modes:
  - Basic (current): keyword-based, no API keys needed - keep as default fallback
  - LLM: use providers if any configured/tested ready; fallback gracefully
- Update `jarvis/assistant.py`: add `use_llm` mode, detect if providers configured
- Update chat to prefer LLM when available, explain fallback if none

### 4. API Server (FastAPI) for Settings/Integration
Add `jarvis/app.py` (or `server.py`) with endpoints matching Atif's API for interoperability:
- `GET /api/health` - health check
- `GET /api/settings` - get non-provider settings (provider keys never returned)
- `POST /api/settings` - save settings (skip provider.*)
- `GET /api/providers` - list providers with masked keys, ready status
- `POST /api/providers/{name}` - save provider config (api_key/model/url/enabled/clear_key)
- `POST /api/providers/{name}/test` - test specific provider
- `POST /api/providers/test` - test all providers
- `POST /api/ask` - chat endpoint (Atif-compatible for easy integration)
- `GET /` - serve web UI if enabled

Also add CLI: `jarvis serve` or `jarvis server --port 8771` (avoid conflict with Atif on 8770)

### 5. Web UI for Settings & API Keys
Create `jarvis/web/` with:
- `index.html` - settings page for providers/API keys (mirroring Atif's settings panel)
- `app.js` - handle provider CRUD, testing, masking
- `style.css` - styling
- API calls to `/api/providers` endpoints

UI should allow: toggle provider on/off, enter API key (password field), set model, test single/all, clear key. Show masked key when saved.

### 6. Connect Jarvis to Atif Assistant
Two approaches:
**A. Client mode (consume Atif API):**
- Add config: `ATIF_ASSISTANT_URL` (default http://127.0.0.1:8770)
- Add `jarvis atif status` - check if Atif is running
- Add `jarvis atif chat` - chat via Atif's `/api/ask` endpoint
- In assistant, add option to route through Atif when available/configured
- CLI flag: `--atif` or env var `JARVIS_USE_ATIF=1`

**B. Shared backend / compatibility:**
- Make Jarvis's `/api/ask` endpoint compatible with Atif's request/response format
- This allows Atif UI to potentially talk to Jarvis or vice versa
- Shared understanding of session, routing, labels

**C. Bridge command:**
- `jarvis link atif` - configure connection to Atif instance
- Store Atif URL in settings

Implementation: add `jarvis/atif_client.py` with methods to call Atif API, handle errors gracefully.

### 7. Migration Path
- On first run with new DB, detect if JSON files exist (data/notes.json, tasks.json, memory.json)
- Offer to migrate: copy data preserving IDs/timestamps
- Keep JSON files as backup or remove after successful migration
- Backward compatible: CLI commands still work the same way
- Add `jarvis migrate` command to run migration explicitly

## Implementation Phases (Recommended Order)

| Phase | Focus | Deliverables | Priority |
|---|---|---|---|
| Phase 1 | DB + Settings | jarvis/db.py, settings CRUD, CLI settings commands | High |
| Phase 2 | Providers + API Keys | jarvis/llm.py, provider management, key masking, test endpoints | High |
| Phase 3 | LLM Integration | Update assistant/chat to use LLM with fallback | High |
| Phase 4 | API Server | jarvis/app.py with FastAPI, endpoints for settings/providers/ask | High |
| Phase 5 | Web UI | web/ files for settings UI (providers, API keys management) | Medium |
| Phase 6 | Atif Integration | jarvis/atif_client.py, connect commands, detect Atif running | High |
| Phase 7 | Migration | JSON→SQLite migration, preserve backward compatibility | Medium |
| Phase 8 | Polish | Enhanced assistant with routing/engine, docs, tests | Low |

## Example Usage After Implementation

### Managing API Keys
```bash
# View current settings (keys masked)
jarvis settings

# Set provider API key
jarvis settings set provider.groq.api_key sk-xxx...

# Enable/disable provider
jarvis settings set provider.ollama.enabled false

# List providers with status
jarvis providers

# Test all providers
jarvis providers test
```

### Server Mode (API + Web UI)
```bash
# Start Jarvis as API server (like Atif)
jarvis serve --port 8771

# Open in browser for settings UI
open http://127.0.0.1:8771
```

### Connect to Atif Assistant
```bash
# Check if Atif is running
jarvis atif status

# Chat via Atif
jarvis atif chat

# Configure Atif URL
jarvis settings set atif.url http://localhost:8770
```

### Enhanced Chat
```bash
# Uses LLM if providers configured, falls back to basic
jarvis chat

# Force basic mode
jarvis chat --basic

# Force LLM mode
jarvis chat --llm
```

## Testing Strategy
1. Unit tests for db operations, settings, masking
2. Provider key storage/retrieval with DB override vs env
3. API key masking (never expose full keys)
4. Provider test endpoints (with/without keys)
5. Fallback behavior when no providers configured
6. Migration from JSON to SQLite
7. Atif connectivity (mock server tests)
8. Backward compatibility - existing CLI commands still work

## Key Design Principles
- **Security**: API keys never returned in full; masked in API/UI; stored in SQLite locally
- **Flexibility**: DB overrides env (can clear in UI even if env set)
- **Graceful degradation**: Basic mode always works without external dependencies
- **Interoperability**: API endpoints compatible with Atif where possible
- **Local-first**: All data stays local by default
- **Backward compatible**: Existing commands and data preserved

## Notes from Atif Analysis (relevant for implementation)
- Settings stored in SQLite, provider.* keys excluded from general settings GET
- Keys can be cleared by setting empty or via clear_key flag
- Live readiness requires probing (not just presence) - cache results
- Provider order configurable via env, DB can override models/enabled
- Masking shows last 4 chars only

## Recommendation
Start with Phase 1-4 (DB, providers, LLM, API server) as core. Phase 5-6 add UI and Atif integration. This matches the user's request: "connect it with atif assistant and create an api key system (i can customize this all insetting so avail all the optioin in setting)"

The API key system with full settings customization is covered in Phases 1-2-4-5; Atif connection in Phase 6.
