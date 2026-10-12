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
