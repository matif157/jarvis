# Phase 0 Audit - Jarvis

## Current State (What works)
- Version 0.2.0. CLI via `python3 main.py` with commands: chat, note, task, memory, weather, status, start, settings, providers, serve, atif, migrate
- Data backed by SQLite (`jarvis.db`) in data dir; migration from JSON available
- Notes, tasks, memory persist in SQLite; legacy JSON files still exist as data source
- Multi-provider LLM abstraction (Groq, Gemini, OpenRouter, Ollama) with DB/env overrides, masking, live probing, fallback
- Assistant supports auto/basic/llm/atif modes; routes to Atif if reachable, else LLM if configured, else basic
- API server (FastAPI) with endpoints: /api/health, /api/ask, /api/settings, /api/providers, /api/providers/test, /api/providers/{name}, /api/providers/{name}/test
- Web UI for settings/providers/API keys management
- Atif Assistant integration (client) to bridge to existing Atif instance
- Basic tests updated for v0.2.0

## Incomplete/Mocked
- Weather is mocked (static values)
- Basic assistant is rule-based; LLM mode requires provider keys
- Atif connection depends on external Atif instance running
- Voice, web search, macOS automation, file indexing, job/app workflows not yet implemented (planned)
- Some CLI subcommands are minimal (memory/task only show state or create single item)

## Preserve
- Existing CLI UX and commands; backward compatible (JSON→SQLite migration)
- Data in data/ (migrated/retained)
- Core structure extended modularly

## Architecture
Modular: cli, core, memory, tasks, db, llm, assistant, atif_client, app, config, migrate, weather. Tool registry to be expanded; memory/planner/macOS integration to follow.

## Tech choices
- Python (simple, macOS native), click+rich, httpx, fastapi+uvicorn, sqlite3 (stdlib) - minimal deps

## Next Phase
Phase 1: strengthen foundation (config/env validation, logging, permission model, task execution framework, tool registry base). Keep changes incremental.
