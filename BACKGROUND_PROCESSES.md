# BACKGROUND_PROCESSES.md
Date: 2026-10-13

## Heavy/active background processes (found)
- **OpenCode (AI IDE):** /Applications/OpenCode.app helper processes (GPU/renderer/network) — running; likely main IDE; can be heavy depending on usage
- **Ollama serve + llama3.2:1b:** running at localhost:11434; model loaded (GPU 100%). Consumes RAM/GPU when loaded
- **Atif Assistant (uvicorn):** atif-assistant running on 127.0.0.1:8770 (was running; stopped during cleanup)
- **Jarvis serve (historical):** two instances on ports 8788/8799 (stopped during cleanup)
- **Tailscale:** background networking
- **Other system:** various daemons

## Why heavy?
- OpenCode renderer/GPU helper + Ollama with model loaded in GPU (llama3.2:1b context 4096) consume CPU/GPU/memory
- Multiple uvicorn/serve processes add overhead

## Actions taken
- Stopped Atif Assistant (PID 79609) on port 8770
- Stopped Jarvis serve instances on 8788/8799
- Left Ollama + OpenCode running as they may be actively used (user preference)

Note: Ollama model remains loaded; to free GPU/RAM fully, run `ollama stop llama3.2:1b` or `ollama ps` to check.
