"""Phase 24 — consent-gated device control through the Android AccessibilityService.

The Java service/bridge is replaced by a fake that mirrors the JSON-in/
JSON-out static API (``status()`` / ``action(json)``). Consent has two
halves - the in-app ``device.enabled`` toggle and the Android accessibility
grant - and every action that reaches the bridge must land in the audit
log. Isolation uses a throwaway SQLite file (the runner has no pytest
fixtures), same pattern as Phases 21/22.
"""

import contextlib
import json
import shutil
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from jarvis import db, device_control
from jarvis.app import app
from jarvis.tools import get_enhanced_registry

ROOT = Path(__file__).resolve().parents[1]
ANDROID_SRC = ROOT / "mobile/android/app/src/main"
NOT_RUNNING = (
    "accessibility service not running - enable Jarvis under Android "
    "Settings > Accessibility"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def fresh_device():
    """Isolated DB + clean module state for one test."""
    original = db.DB_PATH
    tmp = Path(tempfile.mkdtemp(prefix="jv24-", dir="."))
    db.DB_PATH = tmp / "jarvis.db"
    db.init_db()
    device_control.clear_backend()
    device_control.reset_state()
    try:
        yield tmp
    finally:
        db.DB_PATH = original
        device_control.clear_backend()
        device_control.reset_state()
        shutil.rmtree(tmp, ignore_errors=True)


class FakeDeviceBridge:
    """Mirrors ai.jarvis.assistant.device.DeviceBridge (static methods)."""

    def __init__(self):
        self.running = True
        self.foreground = "com.whatsapp"
        self.fail = None  # error string every action returns when set
        self.calls = []

    def status(self):
        return {
            "ok": True,
            "supported": True,
            "running": self.running,
            "foreground": self.foreground if self.running else "",
        }

    def action(self, request_json):
        request = json.loads(request_json)
        self.calls.append(request)
        if self.fail:
            return {"ok": False, "error": self.fail}
        if not self.running:
            return {"ok": False, "error": NOT_RUNNING}
        return {"ok": True, "action": request.get("action", ""), "request": request}


def client():
    return TestClient(app)


def raised(fn, *args, **kwargs):
    """Call fn and return the DeviceError it must raise."""
    try:
        fn(*args, **kwargs)
    except device_control.DeviceError as exc:
        return exc
    raise AssertionError(f"{fn.__name__} did not raise DeviceError")


# 1
def test_status_offline_is_honest():
    with fresh_device():
        data = device_control.status_payload()
        assert data["ok"] is True and data["supported"] is False
        assert data["enabled"] is False and data["running"] is False
        assert data["foreground"] == "" and data["audit"] == 0
        assert "Android app" in data["note"]
        assert device_control.is_supported() is False
        assert device_control.get_enabled() is False
        assert "back" in data["actions"] and "type" in data["actions"]


# 2
def test_consent_gate_blocks_before_the_bridge():
    with fresh_device():
        fake = FakeDeviceBridge()
        device_control.set_backend(fake)

        # master toggle off -> 403, the bridge is never touched
        exc = raised(device_control.run_action, "back")
        assert exc.status == 403 and "Settings > Device control" in str(exc)
        assert fake.calls == [] and device_control.audit_count() == 0

        # toggle on but no Android bridge -> 409, still nothing executed
        device_control.set_enabled(True)
        device_control.clear_backend()
        exc = raised(device_control.run_action, "back")
        assert exc.status == 409 and "Android app" in str(exc)
        assert device_control.audit_count() == 0

        # settings roundtrip
        effective = device_control.apply_settings(enabled=False)
        assert effective["enabled"] is False and device_control.get_enabled() is False
        assert effective["supported"] is False
        assert set(effective["actions"]) >= {"screen", "tap", "type"}


# 3
def test_action_validation_never_reaches_the_bridge():
    with fresh_device():
        fake = FakeDeviceBridge()
        device_control.set_backend(fake)
        device_control.set_enabled(True)

        cases = [
            ("wat", {}, "unknown action"),
            ("tap", {}, "x and y"),
            ("tap", {"x": -1, "y": 5}, ">= 0"),
            ("click_node", {}, "index"),
            ("click_node", {"index": -2}, ">= 0"),
            ("scroll", {"direction": "sideways"}, "up, down, left, right"),
            ("type", {"text": "   "}, "non-empty"),
            ("type", {"text": "a" * 2001}, "2000 characters"),
            ("screen", {"max_chars": "abc"}, "integer"),
            ("nodes", {"max_nodes": None}, "integer"),
        ]
        for action, params, fragment in cases:
            exc = raised(device_control.run_action, action, params)
            assert exc.status == 400, (action, params, exc)
            assert fragment in str(exc), (action, params, str(exc))

        assert fake.calls == [] and device_control.audit_count() == 0


# 4
def test_actions_dispatch_and_are_audited():
    with fresh_device():
        fake = FakeDeviceBridge()
        device_control.set_backend(fake)
        device_control.set_enabled(True)

        assert device_control.run_action("back")["ok"] is True
        assert device_control.run_action("lock")["ok"] is True
        device_control.screen_text(max_chars=999999)
        device_control.list_nodes(max_nodes=10000)
        device_control.tap(10, 20)
        device_control.scroll(" DOWN ")
        device_control.type_text("salam bhai")
        device_control.click_node(3)

        # exact whitelist: no extra keys ride along to the bridge
        assert fake.calls[0] == {"action": "back"}
        assert fake.calls[2] == {"action": "screen", "max_chars": 8000}
        assert fake.calls[3] == {"action": "nodes", "max_nodes": 300}
        assert fake.calls[4] == {"action": "tap", "x": 10, "y": 20}
        assert fake.calls[5] == {"action": "scroll", "direction": "down"}
        assert fake.calls[6] == {"action": "type", "text": "salam bhai"}
        assert fake.calls[7] == {"action": "click_node", "index": 3}

        assert device_control.audit_count() == 8
        rows = device_control.audit_log(50)
        assert len(rows) == 8
        assert rows[0]["action"] == "click_node"  # newest first
        assert all(r["ok"] is True for r in rows)
        tap_row = next(r for r in rows if r["action"] == "tap")
        assert json.loads(tap_row["params"]) == {"x": 10, "y": 20}


# 5
def test_bridge_failure_is_audited_and_reported():
    with fresh_device():
        fake = FakeDeviceBridge()
        fake.fail = "gesture was not accepted (tap at 1,2)"
        device_control.set_backend(fake)
        device_control.set_enabled(True)

        exc = raised(device_control.run_action, "tap", {"x": 1, "y": 2})
        assert exc.status == 409 and "gesture was not accepted" in str(exc)

        rows = device_control.audit_log(10)
        assert len(rows) == 1 and rows[0]["ok"] is False
        assert rows[0]["action"] == "tap"
        assert "gesture was not accepted" in rows[0]["error"]
        assert json.loads(rows[0]["params"]) == {"x": 1, "y": 2}


# 6
def test_service_off_reports_honestly():
    with fresh_device():
        fake = FakeDeviceBridge()
        fake.running = False
        device_control.set_backend(fake)
        device_control.set_enabled(True)

        status = device_control.status_payload()
        assert status["running"] is False and status["foreground"] == ""
        assert "GRANT ACCESS" in status["note"]

        exc = raised(device_control.run_action, "back")
        assert exc.status == 409 and "Settings > Accessibility" in str(exc)
        assert device_control.audit_log(10)[0]["ok"] is False


# 7
def test_http_endpoints_full_flow():
    with fresh_device():
        fake = FakeDeviceBridge()
        device_control.set_backend(fake)
        c = client()

        r = c.get("/api/device/status")
        assert r.status_code == 200
        data = r.json()
        assert data["supported"] is True and data["enabled"] is False
        assert data["running"] is True and data["foreground"] == "com.whatsapp"

        # action while the master toggle is off -> 403, not executed
        r = c.post("/api/device/action", json={"action": "back"})
        assert r.status_code == 403 and r.json()["ok"] is False
        assert fake.calls == []

        r = c.post("/api/device/settings", json={"enabled": True})
        assert r.status_code == 200 and r.json()["enabled"] is True

        r = c.post("/api/device/action", json={"action": "back"})
        assert r.status_code == 200 and r.json()["ok"] is True

        r = c.post(
            "/api/device/action", json={"action": "screen", "max_chars": 1000}
        )
        assert r.status_code == 200 and r.json()["action"] == "screen"

        # validation errors stay client errors
        assert c.post("/api/device/action", json={"action": "wat"}).status_code == 400
        assert c.post("/api/device/action", json={"action": "tap"}).status_code == 400
        assert (
            c.post("/api/device/action", json={"action": "type", "text": ""}).status_code
            == 400
        )

        r = c.get("/api/device/audit")
        audit = r.json()
        assert audit["ok"] is True and audit["count"] == 2 and audit["total"] == 2
        assert audit["entries"][0]["action"] == "screen"  # newest first
        assert all(e["ok"] is True for e in audit["entries"])
        assert "T" in audit["entries"][0]["ts"]  # ISO timestamp present

        # toggling off re-arms the gate
        c.post("/api/device/settings", json={"enabled": False})
        r = c.post("/api/device/action", json={"action": "back"})
        assert r.status_code == 403


# 8
def test_java_sources_declare_the_service():
    manifest = (ANDROID_SRC / "AndroidManifest.xml").read_text(encoding="utf-8")
    assert "android.permission.BIND_ACCESSIBILITY_SERVICE" in manifest
    assert ".device.DeviceControlService" in manifest
    assert "@xml/accessibility_service_config" in manifest

    config = ANDROID_SRC / "res/xml/accessibility_service_config.xml"
    assert config.exists()
    text = config.read_text(encoding="utf-8")
    assert 'android:canRetrieveWindowContent="true"' in text
    assert 'android:canPerformGestures="true"' in text

    service = (
        ANDROID_SRC / "java/ai/jarvis/assistant/device/DeviceControlService.java"
    ).read_text(encoding="utf-8")
    assert "extends AccessibilityService" in service
    assert "performGlobalAction" in service
    assert "getRootInActiveWindow" in service
    assert "ACTION_SET_TEXT" in service
    assert "dispatchGesture" in service
    assert "onUnbind" in service  # instance cleared when the user revokes access

    bridge = ANDROID_SRC / "java/ai/jarvis/assistant/device/DeviceBridge.java"
    bridge_text = bridge.read_text(encoding="utf-8")
    assert 'case "tap"' in bridge_text and 'case "screen"' in bridge_text
    assert 'case "type"' in bridge_text and 'case "back"' in bridge_text
    assert "DeviceControlService.NOT_RUNNING" in bridge_text

    main = (ANDROID_SRC / "java/ai/jarvis/assistant/MainActivity.java").read_text(
        encoding="utf-8"
    )
    assert "openAccessibilitySettings" in main
    assert "ACTION_ACCESSIBILITY_SETTINGS" in main


# 9
def test_device_tools_go_through_the_same_gate():
    with fresh_device():
        fake = FakeDeviceBridge()
        device_control.set_backend(fake)
        reg = get_enhanced_registry()

        status_tool = reg.get("device.status")
        tap_tool = reg.get("device.tap")
        screen_tool = reg.get("device.screen")
        assert status_tool is not None and tap_tool is not None
        assert screen_tool is not None
        assert "device.control" in tap_tool.permissions
        assert "device.read" in status_tool.permissions

        # consent off: the tool fails honestly and the bridge stays idle
        res = tap_tool.run(x=1, y=2)
        assert res.success is False and "Settings > Device control" in res.error
        assert fake.calls == []

        device_control.set_enabled(True)
        res = tap_tool.run(x=1, y=2)
        assert res.success is True and res.result["ok"] is True
        res = status_tool.run()
        assert res.success is True and res.result["supported"] is True

        # through the registry: device.control is confirmation-gated by default
        calls_before = len(fake.calls)
        res = reg.execute("device.tap", x=5, y=6)
        assert res.success is False and "confirmation required" in res.error
        assert len(fake.calls) == calls_before  # blocked before the bridge
        res = reg.execute("device.tap", x=5, y=6, confirm=True)
        assert res.success is True and fake.calls[-1]["action"] == "tap"

        # service not granted: screen tool surfaces the Android-side reason
        fake.running = False
        res = screen_tool.run()
        assert res.success is False and "Settings > Accessibility" in res.error
        assert device_control.audit_log(10)[0]["ok"] is False
