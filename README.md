# Jarvis — Personal Assistant

Jarvis is a **local-first personal AI assistant** for macOS. It chats, plans,
and executes real tasks through a single tool-calling loop — managing memory,
tasks, notes, files, the web, email, career documents, voice, home devices,
and resumable multi-step workflows. Consequential actions require explicit
confirmation, secrets are never logged, and your data stays on disk under
`data/` and `config/`.

Current release: **v1.0.0** (see `RELEASE_NOTES.md` and `CHANGELOG.md`).

## Features

- **Local-first & private** — runs on your machine; all data stays local.
- **Multi-provider AI** — Groq, Gemini, OpenRouter, and Ollama, with an offline
  "basic" fallback and an optional Atif Assistant bridge.
- **Reliable action loop** — tool selection, multi-step execution, permission
  gating, and confirmation for destructive actions.
- **Productivity** — tasks, notes, and trusted memory with context injection.
- **macOS actions** — open apps/URLs, reveal files, create files (safely).
- **Web research** — source-linked answers with an offline mock mode.
- **Integrations** — Google Drive, resume/career helpers, and email
  (opt-in, credential-gated).
- **Job workflow** — discovery and application tracking with a status machine.
- **Voice** — macOS `say` text-to-speech plus optional, pluggable speech-to-text.
- **API + web UI** — JSON endpoints for tools, chat, and status, plus a
  three-tab web console (Chat / Tools / Settings).
- **Resumable workflows** — persistent multi-step plans that survive restarts.
- **Atif bridge & IoT** — forward questions to an Atif Assistant and control
  registered smart devices (mock / HTTP / Home Assistant).

## Requirements

- Python 3.9 – 3.12
- macOS for full functionality (core assistant works cross-platform with
  reduced system-action support)
- Optional: a local [Ollama](https://ollama.com) server, or API keys for cloud
  providers

## Install

```bash
git clone https://github.com/matif157/jarvis.git
cd jarvis

pip install -r requirements.txt
pip install -e .          # provides the `jarvis` command
```

Development extras (tests, build tooling):

```bash
pip install -r requirements-dev.txt
```

## Quick start

```bash
python3 main.py status          # health + provider status
python3 main.py chat            # interactive conversation
python3 main.py serve           # web UI at http://127.0.0.1:8771
```

Or with the installed console script:

```bash
jarvis status
jarvis chat
jarvis serve
```

Copy `.env.example` to `.env` to configure providers, ports, and the Atif bridge.

## Usage

```bash
# Assistant
jarvis chat                      # conversation with tool-calling
jarvis status                    # system + provider status

# Server & UI
jarvis serve                     # JSON API + web console

# Workflows
jarvis workflow list
jarvis workflow create myplan --goal "..." --step "weather.get:city=London"
jarvis workflow run <id>
jarvis workflow resume <id>

# IoT devices
jarvis iot providers
jarvis iot list
jarvis iot add lamp --provider mock --kind light
jarvis iot control lamp on

# Atif Assistant bridge
jarvis atif status
```

## Configuration

Configuration is read from the environment (and an optional `.env`). See
`.env.example` for the full list. Key variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `JARVIS_HOST` | `127.0.0.1` | API/web bind address |
| `JARVIS_PORT` | `8771` | API/web port |
| `JARVIS_PROVIDERS` | `groq,gemini,openrouter,ollama` | Provider preference order |
| `JARVIS_ATIF_URL` | `http://127.0.0.1:8770` | Atif Assistant bridge URL |
| `GROQ_API_KEY` / `GEMINI_API_KEY` / `OPENROUTER_API_KEY` | — | Cloud provider keys |
| `JARVIS_DATA_DIR` / `JARVIS_CONFIG_DIR` | `./data` / `./config` | Local storage |

Optional integrations (Google Drive, email) require your own credentials and
stay disabled until configured.

## Security

- Private content (email, Drive) is treated as **untrusted input**.
- Destructive tools (`file.delete`, `system.configure`, `email.send`,
  `job.apply`, `voice.listen`, `workflow.run`, `iot.control`) require
  explicit confirmation and are gated by the permission system in
  `jarvis/permissions.py`.
- Secrets are never written to logs. Local state lives in `data/` and `config/`
  (both excluded from version control).

## Testing

The suite is dependency-free (no pytest needed):

```bash
make test            # python3 scripts/run_tests.py
make lint            # byte-compile the whole tree
make test-pytest     # same suite via pytest, when installed
```

## Project structure

```
jarvis/
├── jarvis/            # Core package (assistant, tools, api, workflows, iot…)
├── web/               # Web UI (index.html, app.js, style.css)
├── tests/             # Test suite (test_phase*.py)
├── scripts/           # run_tests.py (dependency-free runner)
├── config/            # Local permissions/config
├── data/              # Local data (gitignored)
├── main.py            # Entry point
├── setup.py           # Packaging metadata
├── pyproject.toml     # Build system + tool config
├── Makefile           # Common tasks
└── RELEASING.md       # Release checklist
```

## License

MIT — see `LICENSE`.
