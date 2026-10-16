# Phase 13 Report — Resumable Workflows

## Implemented
- **Workflow module** (`jarvis/workflows.py`): persistent, resumable multi-step plans.

### Model
- `WorkflowStep`: `id`, `tool`, `args`, `description`, `status`, `result`, `error`, `attempts`, `max_retries`, `optional`, `continue_on_error`.
- `Workflow`: `id`, `name`, `goal`, `status`, `steps`, `context`, `tags`, `created_at/updated_at`, `started_at/finished_at`, `error`.
- Lifecycle: `pending → running → (completed | failed | blocked | paused | cancelled)`.

### Persistence (`WorkflowStore`)
- One JSON file per workflow under `data/workflows/<id>.json`, written atomically after **every** step.
- `list(status=, tag=)` and `delete()`; state survives process restarts.

### Engine (`WorkflowEngine`)
| Method | Behavior |
|---|---|
| `create(name, steps, goal, context, tags)` | Build steps with auto ids; returns a `pending` workflow |
| `from_goal(goal)` | Plans steps from a natural-language goal via `Planner` |
| `start(id)` | Runs from the next incomplete step; gated steps set `blocked` |
| `resume(id, confirm)` | Continues a paused/blocked/failed workflow; `confirm` authorizes gated steps |
| `pause(id)` / `cancel(id)` | Manual pause; terminal cancel |
| `get(id)` / `list(...)` / `delete(id)` | Inspection and cleanup |

- **Resumption**: on start/resume the engine skips completed/skipped steps and continues from the next unfinished one — even in a brand-new engine after a restart.
- **Retries/robustness**: `max_retries` (attempts recorded), `optional` (failure → skipped, workflow continues), `continue_on_error` (records failure, continues).
- **Data flow**: `${goal}`, `${context.<key>}`, `${steps.<id>.result[.<path>]}`, `${steps.<id>.status}` are resolved from prior step results.

## Confirmation & Safety
- Steps run through the standard registry, so permission gating already applies per tool.
- A confirmation-required step (e.g. `email.send`, `voice.listen`) sets the workflow to **blocked** (a resumable checkpoint) rather than running.
- `workflow.run` (used by `resume`) is a destructive permission: resuming/authorizing consequential steps requires explicit confirmation.
- `workflow.read` / `workflow.write` are allowlisted; nothing is fabricated — step results/errors reflect real tool output.
- Unknown workflow ids and invalid lifecycle transitions raise clear errors.

## Tools (9)
`workflow.create`, `workflow.from_goal`, `workflow.list`, `workflow.get`, `workflow.start`, `workflow.resume`, `workflow.pause`, `workflow.cancel`, `workflow.delete` — registered in the enhanced registry (60 tools total).

## CLI
`jarvis workflow list|show|create|run|resume|cancel`. Also fixed a pre-existing misplaced `if __name__ == "__main__"` block in `cli.py` so `python -m jarvis.cli` registers every command.

## Acceptance Tests (27/27 Passed, fully offline)
Dataclass defaults (1–2); store save/load (3), list+filters (4), delete (5); create (6–7); start completes (8); restart persistence (9); interpolation result/goal/context (10–11); gated block (12), resume without confirm stays blocked (13), resume with confirm proceeds honestly (14); resume skips completed (15); optional failure (16); continue_on_error (17); required failure (18); retries (19); pause/resume + cancel (20); unknown id (21); from_goal (22); tool registration (23); permissions + gating (24); tool roundtrip (25); validation (26); summary shape (27).

Tests use a temporary store directory — no network, no audio, no real data written.

## All Tests Pass (267 tests across 28 modules)
