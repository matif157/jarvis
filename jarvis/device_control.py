"""Device control (Phase 24): consent-gated screen actions on Android.

Actions run through an :class:`~android.accessibilityservice.AccessibilityService`
(``DeviceControlService``) reached via the JSON-in/JSON-out static
``DeviceBridge`` - same pattern as the voice and WhatsApp bridges.

Consent has two independent layers, both required before any action runs:

1. the in-app master toggle ``device.enabled`` (default **off**) - Jarvis
   never assumes the user wanted this on;
2. the system accessibility grant - the user flips that in Android
   Settings, and the app only ever *opens* that screen
   (``openAccessibilitySettings()``); it never enables itself.

Every action that reaches the bridge is written to the ``device_audit``
table (action, params, ok, error) so exactly what ran can be reviewed.
Requests rejected by the consent gate or by validation raise before the
bridge and are therefore not executed or audited.

Off-device everything degrades honestly: ``supported`` is False and actions
raise ``DeviceError`` with the real reason instead of pretending.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from . import db
from .logging import get_logger

logger = get_logger(__name__)

MAX_TEXT_CHARS = 2000
MAX_SCREEN_CHARS = 8000
DEFAULT_SCREEN_CHARS = 4000
MAX_NODES = 300
DEFAULT_NODES = 200

GLOBAL_ACTIONS = ("back", "home", "recents", "notifications", "quick_settings", "lock")
SCROLL_DIRECTIONS = ("up", "down", "left", "right")
ACTIONS = GLOBAL_ACTIONS + ("screen", "nodes", "tap", "click_node", "scroll", "type")

SETTING_ENABLED = "device.enabled"


class DeviceError(RuntimeError):
    """User-facing device-control failure; ``status`` maps to the HTTP code."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------------
# Android bridge (mirrors the WhatsApp bridge pattern)
# ---------------------------------------------------------------------------
_backend: Optional[Any] = None
_probed = False
_cache: Any = None


def set_backend(backend: Any = None) -> None:
    """Install a bridge stand-in (tests). Mirrors the Java static API."""
    global _backend
    _backend = backend


def clear_backend() -> None:
    global _backend, _cache, _probed
    _backend = None
    _cache = None
    _probed = False


def reset_state() -> None:
    """Drop the bridge cache (tests). Settings and audit live in the DB."""
    global _cache, _probed
    _cache = None
    _probed = False


def _bridge() -> Any:
    global _cache, _probed
    if _backend is not None:
        return _backend
    if not _probed:
        _probed = True
        try:
            from ai.jarvis.assistant.device import DeviceBridge  # type: ignore

            _cache = DeviceBridge
        except Exception:  # noqa: BLE001 - not running inside the Android app
            _cache = None
    return _cache


def is_supported() -> bool:
    """True when running inside the Android app (bridge importable)."""
    return _bridge() is not None


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, str):
        try:
            data = json.loads(value)
            return data if isinstance(data, dict) else {"ok": False, "error": "bad bridge payload"}
        except Exception:  # noqa: BLE001
            return {"ok": False, "error": value[:200]}
    if isinstance(value, dict):
        return value
    return {"ok": False, "error": "unexpected bridge return"}


def _call(bridge: Any, method: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    fn = getattr(bridge, method)
    try:
        raw = fn(json.dumps(payload)) if payload is not None else fn()
    except Exception as exc:  # noqa: BLE001
        raise DeviceError(f"device bridge failed: {exc}", 409) from exc
    data = _as_dict(raw)
    if not data.get("ok"):
        # bridge-side refusals mean the service is unavailable, not a bad request
        raise DeviceError(str(data.get("error") or "device bridge error"), 409)
    return data


# ---------------------------------------------------------------------------
# Settings (the in-app half of the consent gate)
# ---------------------------------------------------------------------------
def get_enabled() -> bool:
    return db.get_setting(SETTING_ENABLED, "0") == "1"


def set_enabled(enabled: bool) -> None:
    db.set_setting(SETTING_ENABLED, "1" if enabled else "0")


def apply_settings(enabled: Optional[bool] = None) -> Dict[str, Any]:
    if enabled is not None:
        set_enabled(bool(enabled))
    return settings_payload()


def settings_payload() -> Dict[str, Any]:
    return {
        "enabled": get_enabled(),
        "supported": is_supported(),
        "actions": list(ACTIONS),
    }


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------
def _audit(action: str, params: Dict[str, Any], ok: bool, error: str = "") -> None:
    try:
        db.add_device_audit_db(
            action,
            json.dumps(params, ensure_ascii=False)[:500],
            ok,
            error[:300],
        )
    except Exception as exc:  # noqa: BLE001 - auditing must never break the call
        logger.warning(f"device audit write failed: {exc}")


def audit_log(limit: int = 100) -> List[Dict[str, Any]]:
    return db.list_device_audit_db(limit)


def audit_count() -> int:
    return db.count_device_audit_db()


# ---------------------------------------------------------------------------
# Status (never gated: the user needs it to grant consent)
# ---------------------------------------------------------------------------
def status_payload() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": True,
        "supported": is_supported(),
        "enabled": get_enabled(),
        "running": False,
        "foreground": "",
        "audit": audit_count(),
        "actions": list(ACTIONS),
    }
    bridge = _bridge()
    if bridge is None:
        out["note"] = (
            "On-device control needs the Android app - grant accessibility there "
            "(Settings > Device control)."
        )
        return out
    try:
        data = _call(bridge, "status")
    except DeviceError as exc:
        out["error"] = str(exc)
        return out
    out["running"] = bool(data.get("running"))
    out["foreground"] = str(data.get("foreground") or "")
    if not out["running"]:
        out["note"] = "Accessibility service not granted - tap GRANT ACCESS (Android Settings > Accessibility)."
    return out


# ---------------------------------------------------------------------------
# Action validation (before consent: cheap, and never reaches the bridge)
# ---------------------------------------------------------------------------
def _normalize(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Validate one action's parameters; returns only the keys it uses."""
    if action in GLOBAL_ACTIONS:
        return {}

    if action == "screen":
        value = params.get("max_chars", DEFAULT_SCREEN_CHARS)
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise DeviceError("max_chars must be an integer", 400) from None
        return {"max_chars": max(100, min(value, MAX_SCREEN_CHARS))}

    if action == "nodes":
        value = params.get("max_nodes", DEFAULT_NODES)
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise DeviceError("max_nodes must be an integer", 400) from None
        return {"max_nodes": max(1, min(value, MAX_NODES))}

    if action == "tap":
        try:
            x = int(params.get("x"))  # type: ignore[arg-type]
            y = int(params.get("y"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise DeviceError("tap requires x and y (screen pixels)", 400) from None
        if x < 0 or y < 0:
            raise DeviceError("tap x and y must be >= 0", 400)
        return {"x": x, "y": y}

    if action == "click_node":
        try:
            index = int(params.get("index"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise DeviceError("click_node requires the node index from device.nodes", 400) from None
        if index < 0:
            raise DeviceError("node index must be >= 0", 400)
        return {"index": index}

    if action == "scroll":
        direction = str(params.get("direction") or "").strip().lower()
        if direction not in SCROLL_DIRECTIONS:
            raise DeviceError(
                f"scroll direction must be one of: {', '.join(SCROLL_DIRECTIONS)}", 400
            )
        return {"direction": direction}

    if action == "type":
        text = params.get("text")
        if not isinstance(text, str) or not text.strip():
            raise DeviceError("type requires non-empty text", 400)
        if len(text) > MAX_TEXT_CHARS:
            raise DeviceError(f"type text is limited to {MAX_TEXT_CHARS} characters", 400)
        return {"text": text}

    raise DeviceError(f"unknown action '{action}' - allowed: {', '.join(ACTIONS)}", 400)


def _require_consent() -> Any:
    """Both consent layers; returns the bridge. Raises DeviceError otherwise."""
    if not get_enabled():
        raise DeviceError(
            "device control is off - turn it on in Settings > Device control", 403
        )
    bridge = _bridge()
    if bridge is None:
        raise DeviceError("device control needs the Android app", 409)
    return bridge


# ---------------------------------------------------------------------------
# Actions (consent gate -> validate -> dispatch -> audit)
# ---------------------------------------------------------------------------
def run_action(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Execute one device action.

    Order matters: validation and the consent gate raise *before* the bridge,
    so rejected requests never run and never hit the audit log. Everything the
    bridge actually attempted is audited, failures included.
    """
    action = (action or "").strip().lower()
    normalized = _normalize(action, params or {})
    bridge = _require_consent()
    payload: Dict[str, Any] = {"action": action}
    payload.update(normalized)

    try:
        data = _call(bridge, "action", payload)
    except DeviceError as exc:
        _audit(action, normalized, ok=False, error=str(exc))
        raise

    _audit(action, normalized, ok=True)
    data = dict(data)
    data.setdefault("action", action)
    return data


def global_action(name: str) -> Dict[str, Any]:
    """Shorthand for the back/home/recents family."""
    return run_action(name)


def screen_text(max_chars: int = DEFAULT_SCREEN_CHARS) -> Dict[str, Any]:
    return run_action("screen", {"max_chars": max_chars})


def list_nodes(max_nodes: int = DEFAULT_NODES) -> Dict[str, Any]:
    return run_action("nodes", {"max_nodes": max_nodes})


def tap(x: int, y: int) -> Dict[str, Any]:
    return run_action("tap", {"x": x, "y": y})


def click_node(index: int) -> Dict[str, Any]:
    return run_action("click_node", {"index": index})


def scroll(direction: str) -> Dict[str, Any]:
    return run_action("scroll", {"direction": direction})


def type_text(text: str) -> Dict[str, Any]:
    return run_action("type", {"text": text})


# ---------------------------------------------------------------------------
# Tools (Phase 11 registry style)
# ---------------------------------------------------------------------------
def get_device_tools() -> List[Any]:
    """Tools for the chat agent; every one of them goes through the same
    consent gate and audit log as the HTTP endpoints."""
    from .tools import Tool, ToolResult  # local import: tools imports this module

    class DeviceStatusTool(Tool):
        name = "device.status"
        description = "Report device-control support, consent state and audit count"
        permissions = ["device.read"]

        def run(self) -> ToolResult:
            return ToolResult(success=True, result=status_payload(), tool=self.name)

    class DeviceScreenTool(Tool):
        name = "device.screen"
        description = "Read the visible text of the current screen (Android, needs consent)"
        permissions = ["device.read"]

        def run(self, max_chars: int = DEFAULT_SCREEN_CHARS) -> ToolResult:
            try:
                return ToolResult(
                    success=True, result=screen_text(max_chars), tool=self.name
                )
            except DeviceError as exc:
                return ToolResult(success=False, error=str(exc), tool=self.name)

    class DeviceTapTool(Tool):
        name = "device.tap"
        description = "Tap screen coordinates x, y in pixels (Android, needs consent)"
        permissions = ["device.control"]

        def run(self, x: int = -1, y: int = -1) -> ToolResult:
            try:
                return ToolResult(success=True, result=tap(x, y), tool=self.name)
            except DeviceError as exc:
                return ToolResult(success=False, error=str(exc), tool=self.name)

    class DeviceNodeTool(Tool):
        name = "device.node"
        description = "Tap an actionable node by index from device.nodes (Android, needs consent)"
        permissions = ["device.control"]

        def run(self, index: int = -1) -> ToolResult:
            try:
                return ToolResult(success=True, result=click_node(index), tool=self.name)
            except DeviceError as exc:
                return ToolResult(success=False, error=str(exc), tool=self.name)

    class DeviceScrollTool(Tool):
        name = "device.scroll"
        description = "Scroll the current screen up/down/left/right (Android, needs consent)"
        permissions = ["device.control"]

        def run(self, direction: str = "") -> ToolResult:
            try:
                return ToolResult(success=True, result=scroll(direction), tool=self.name)
            except DeviceError as exc:
                return ToolResult(success=False, error=str(exc), tool=self.name)

    class DeviceTypeTool(Tool):
        name = "device.type"
        description = "Type text into the focused field, replacing its content (Android, needs consent)"
        permissions = ["device.control"]

        def run(self, text: str = "") -> ToolResult:
            try:
                return ToolResult(success=True, result=type_text(text), tool=self.name)
            except DeviceError as exc:
                return ToolResult(success=False, error=str(exc), tool=self.name)

    class DeviceGlobalTool(Tool):
        name = "device.global"
        description = "Android global action: back, home, recents, notifications, quick_settings or lock"
        permissions = ["device.control"]

        def run(self, action: str = "") -> ToolResult:
            try:
                return ToolResult(success=True, result=global_action(action), tool=self.name)
            except DeviceError as exc:
                return ToolResult(success=False, error=str(exc), tool=self.name)

    return [
        DeviceStatusTool(),
        DeviceScreenTool(),
        DeviceTapTool(),
        DeviceNodeTool(),
        DeviceScrollTool(),
        DeviceTypeTool(),
        DeviceGlobalTool(),
    ]
