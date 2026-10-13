# Phase 2 Report — Multi-step Action Loop + Confirmations

Date: 2026-10-13
Repo: /Users/husayn/Documents/Default Project/jarvis
Branch: phase-1-llm-routing

## Implemented
- jarvis/action_loop.py: new ActionLoop class. Runs up to max_steps; routes each step via Router; executes tools; appends tool results to context; stops on final chat or error. Confirmations only in interactive mode when tool has permissions (defaults to allow in non-interactive/tests).
- jarvis/assistant.py: wired ActionLoop (non-interactive). In auto/llm modes, try ActionLoop first, fall back to single-shot router if loop doesn't return usable chat. Restored answer_with_tools and deduped start (from Phase 1 fixes).
- tests/test_action_loop.py: deterministic tests for single-shot chat, tool-then-chat, tool-fails.

## Behavior
- Single-shot chat returns immediately.
- Tool-then-chat: first step calls tool, second returns final answer.
- Failures return error message.
- Existing behavior preserved for atif/basic modes.

## Tests
- All existing tests still pass.
- New action loop deterministic tests pass.
- Live sanity: llm mode returns exact token; time query still works.

## Deferred
- Interactive confirmations UI polish, retries with backoff, multi-tool sequences in one step, native tool_calls.
