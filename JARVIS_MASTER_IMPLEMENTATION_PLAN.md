# JARVIS — Master Implementation Plan

Mission: Turn Jarvis into a practical, trustworthy macOS personal AI agent — local-first, tool-using, permission-aware, verifiable. Keep working components, inspect before editing, no rebuild.

Principles: actual work over chat; local-first/cost-aware (Ollama default); one reliable action loop; human control for consequential actions; reuse existing code; secure by default; observable/recoverable; no fake capabilities; ask only when genuinely needed.

## Phases (0-15) summary
0 Baseline/backups/acceptance; 1 Real LLM in normal chat; 2 LLM tool calling + action loop; 3 Productivity tools; 4 Memory/context trust; 5 macOS safe actions; 6 Web search/research; 7 Google Drive; 8 Resume/career; 9 Email/messaging with consent; 10 Job discovery/app workflow; 11 Voice; 12 API/web UI; 13 Resumable workflows; 14 Atif bridge/IoT optional; 15 Release readiness.

First task: Phase 0 + Phase 1 — verify normal chat uses Ollama, and prove model selects a real registered tool with result returned. Stop after each phase, report evidence.

## Current state (evidence)
- Repo: /Users/husayn/Documents/Default Project/jarvis (branch main, commit 4b55933)
- Python 3.9.6, v0.2.0, SQLite data/jarvis.db
- Ollama live: localhost:11434, model llama3.2:1b — llm.complete() returns "JARVIS_LLM_OK" (verified)
- Atif (8770): not used live; health unreachable when checked; client exists
- 8 tests pass (agent/basic/conversation/engine/memory_enhanced/migrate/security/tools)
- CLI/tools/planner/agent/fs tools/security/migration exist
