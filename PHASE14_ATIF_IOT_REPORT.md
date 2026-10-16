# Phase 14 Report — Atif Bridge / IoT (optional)

## Implemented

### Atif bridge (`jarvis/atif_client.py`)
The existing async client was complemented with **synchronous** bridge helpers + tools (tools run synchronously, even from the async action loop, so blocking HTTP is correct here):

| Tool | Permission | Behavior |
|---|---|---|
| `atif.status` | `atif.read` | Bridge URL, reachability, active answer mode |
| `atif.ask` | `atif.ask` | Forward a question to Atif (`{question, session}` — matches its `Ask` schema); honest failure when unreachable |
| `atif.set_url` | `atif.config` | Configure the bridge URL (http/https validated, persisted to settings) |

- Base URL resolution is unchanged: DB override (`atif.url`) → env `JARVIS_ATIF_URL` → default `http://127.0.0.1:8770`.
- **Live verification**: an Atif Assistant was actually running on `127.0.0.1:8770`; `atif.status` returned real data (provider readiness, memory counts, speech backends). Marked *integration-verified for health/status*. Live `ask` is slower than the 3s health probe, so it is unit-tested (patched) rather than user-flow verified.

### IoT (`jarvis/iot.py`) — optional, local-first
- `Device` (id, name, provider, kind, address, state, capabilities) + `DeviceStore` (JSON under `data/iot/devices.json`, CRUD + persisted state).
- Pluggable providers via a `DeviceProvider` ABC:
  - `MockDeviceProvider` — in-memory, deterministic (tests/demos).
  - `HttpDeviceProvider` — generic REST: POST `{action, value}` to the device address; addresses restricted to **http/https**.
  - `HomeAssistantProvider` — Home Assistant REST API; used **only** when `iot.home_assistant.url` + `.token` are configured, otherwise honest "not configured".
- `IoTManager` resolves the device's provider and executes `on/off/toggle/set/status`, persisting resulting state.

## Safety
- **Nothing is contacted** unless a device is registered *and* explicitly controlled.
- `iot.control` is confirmation-gated (destructive); `iot.read`/`iot.write` are allowlisted; `atif.read/ask/config` allowlisted.
- Device addresses are validated to http/https; unknown providers/devices/actions return clear errors; no device state is fabricated.

## Tools (9 total this phase)
Atif: `atif.status`, `atif.ask`, `atif.set_url`.
IoT: `iot.providers`, `iot.devices`, `iot.add_device`, `iot.remove_device`, `iot.status`, `iot.control`.
Registered in the enhanced registry — **69 tools total**.

## CLI
- New `jarvis iot providers|list|add|control|remove`.
- Existing `jarvis atif status|url|chat` retained.

## Acceptance Tests (22/22 Passed, fully offline)
Atif: status reachable/unreachable (1–2), ask success/honest-failure (3–4), ask requires question (5), set_url scheme validation (6), set_url persists (7), tools registered (8).
IoT: device defaults (9), store roundtrip/update/remove (10), mock provider actions (11), manager control+state (12), validation (13), control errors (14), http unsafe URL (15), http unreachable honest (16), home_assistant honest (17), provider status (18), `iot.control` gated (19), registration+permissions (20), registry roundtrip (21), providers tool (22).

Network helpers are patched with `unittest.mock`; the IoT store uses a temp path. No network, no real devices.

## All Tests Pass (289 tests across 29 modules)
