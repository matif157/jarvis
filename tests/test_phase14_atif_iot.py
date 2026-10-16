"""Phase 14 Atif bridge + IoT Tests (offline; network helpers patched)."""

import tempfile
from pathlib import Path
from unittest import mock

from jarvis import atif_client
from jarvis.atif_client import (
    AtifAskTool,
    AtifSetUrlTool,
    AtifStatusTool,
    get_atif_tools,
)
from jarvis.iot import (
    Device,
    DeviceStore,
    HttpDeviceProvider,
    HomeAssistantProvider,
    IoTManager,
    MockDeviceProvider,
    get_iot_tools,
)
from jarvis.permissions import PermissionManager


def make_iot():
    d = tempfile.mkdtemp(prefix="iot_test_")
    return IoTManager(store=DeviceStore(path=Path(d) / "devices.json"))


# --------------------------------------------------------------- Atif bridge
# 1
def test_atif_status_reachable_patched():
    with mock.patch.object(atif_client, "health_sync", return_value={"ok": True, "url": "http://x", "data": {"ok": True}}):
        res = AtifStatusTool().run()
    assert res.success
    assert res.result["reachable"] is True
    assert res.result["url"] == "http://x"
    print("✓ Test 1 PASSED: atif.status reports reachability")


# 2
def test_atif_status_unreachable_patched():
    with mock.patch.object(atif_client, "health_sync", return_value={"ok": False, "url": "http://x", "error": "boom"}):
        res = AtifStatusTool().run()
    assert res.success
    assert res.result["reachable"] is False
    assert res.result["error"] == "boom"
    print("✓ Test 2 PASSED: atif.status honest when unreachable")


# 3
def test_atif_ask_success_patched():
    with mock.patch.object(atif_client, "ask_sync", return_value={"ok": True, "url": "http://x", "data": {"text": "hello"}}):
        res = AtifAskTool().run(question="hi")
    assert res.success
    assert res.result["text"] == "hello"
    print("✓ Test 3 PASSED: atif.ask returns text")


# 4
def test_atif_ask_honest_failure_patched():
    with mock.patch.object(atif_client, "ask_sync", return_value={"ok": False, "url": "http://x", "error": "refused"}):
        res = AtifAskTool().run(question="hi")
    assert res.success is False
    assert "unreachable" in res.error
    print("✓ Test 4 PASSED: atif.ask honest failure")


# 5
def test_atif_ask_requires_question():
    res = AtifAskTool().run(question="  ")
    assert res.success is False
    print("✓ Test 5 PASSED: atif.ask requires a question")


# 6
def test_atif_set_url_validates_scheme():
    assert AtifSetUrlTool().run(url="ftp://x").success is False
    assert AtifSetUrlTool().run(url="").success is False
    print("✓ Test 6 PASSED: atif.set_url rejects non-http(s)")


# 7
def test_atif_set_url_persists_and_cleans():
    from jarvis import db

    res = AtifSetUrlTool().run(url="http://127.0.0.1:9999")
    assert res.success
    assert db.get_setting("atif.url") == "http://127.0.0.1:9999"
    db.delete_setting("atif.url")
    print("✓ Test 7 PASSED: atif.set_url writes the setting")


# 8
def test_atif_tools_registered():
    from jarvis.tools import get_enhanced_registry

    names = {t["name"] for t in get_enhanced_registry().list_tools()}
    assert {"atif.status", "atif.ask", "atif.set_url"}.issubset(names)
    assert len(get_atif_tools()) == 3
    print("✓ Test 8 PASSED: atif tools registered")


# ---------------------------------------------------------------------- IoT
# 9
def test_device_defaults():
    d = Device(id="d1", name="Lamp")
    assert d.provider == "mock"
    assert d.capabilities == ["on", "off", "toggle"]
    assert d.created_at
    print("✓ Test 9 PASSED: Device defaults")


# 10
def test_device_store_roundtrip():
    d = tempfile.mkdtemp(prefix="iot_test_")
    store = DeviceStore(path=Path(d) / "devices.json")
    dev = Device(id="dev_1", name="Lamp", provider="mock")
    store.add(dev)
    assert store.get("dev_1").name == "Lamp"
    assert len(store.list()) == 1
    dev.state = {"power": "on"}
    store.update(dev)
    reloaded = DeviceStore(path=Path(d) / "devices.json")
    assert reloaded.get("dev_1").state == {"power": "on"}
    assert store.remove("dev_1") is True
    assert store.remove("dev_1") is False
    print("✓ Test 10 PASSED: DeviceStore roundtrip/update/remove")


# 11
def test_mock_provider_actions():
    p = MockDeviceProvider()
    dev = Device(id="d", name="Lamp")
    assert p.control(dev, "on")["state"] == {"power": "on"}
    assert p.control(dev, "toggle")["state"] == {"power": "off"}
    assert p.control(dev, "set", value=42)["state"] == {"power": "off", "value": 42}
    assert p.control(dev, "status")["state"] == dev.state
    assert p.control(dev, "bogus")["ok"] is False
    print("✓ Test 11 PASSED: MockDeviceProvider actions")


# 12
def test_manager_control_and_state():
    mgr = make_iot()
    dev = mgr.add_device(name="Lamp")
    on = mgr.control(dev.id, "on")
    assert on["ok"] and on["state"]["power"] == "on"
    assert mgr.store.get(dev.id).state["power"] == "on"
    assert mgr.control(dev.id, "toggle")["state"]["power"] == "off"
    print("✓ Test 12 PASSED: IoTManager controls and persists state")


# 13
def test_manager_add_device_validation():
    mgr = make_iot()
    try:
        mgr.add_device(name="x", provider="nope")
        assert False
    except ValueError:
        pass
    try:
        mgr.add_device(name="x", provider="http", address="ftp://x")
        assert False
    except ValueError:
        pass
    print("✓ Test 13 PASSED: add_device validates provider/address")


# 14
def test_manager_control_errors():
    mgr = make_iot()
    assert mgr.control("nope", "on")["ok"] is False
    dev = mgr.add_device(name="Lamp")
    assert mgr.control(dev.id, "explode")["ok"] is False
    print("✓ Test 14 PASSED: control reports unknown device/action")


# 15
def test_http_provider_unsafe_url():
    p = HttpDeviceProvider()
    dev = Device(id="d", name="x", provider="http", address="ftp://host/x")
    r = p.control(dev, "on")
    assert r["ok"] is False and "http" in r["error"]
    print("✓ Test 15 PASSED: http provider rejects non-http(s) address")


# 16
def test_http_provider_unreachable_is_honest():
    p = HttpDeviceProvider()
    dev = Device(id="d", name="x", provider="http", address="http://127.0.0.1:1/control")
    r = p.control(dev, "on")
    assert r["ok"] is False and r["error"]
    print("✓ Test 16 PASSED: http provider honest on unreachable endpoint")


# 17
def test_home_assistant_unavailable_by_default():
    p = HomeAssistantProvider("", "")
    assert p.available() is False
    dev = Device(id="d", name="x", provider="home_assistant", address="light.kitchen")
    r = p.control(dev, "on")
    assert r["ok"] is False and "not configured" in r["error"]
    print("✓ Test 17 PASSED: home_assistant honest when unconfigured")


# 18
def test_manager_provider_status():
    mgr = make_iot()
    status = {p["name"]: p["available"] for p in mgr.provider_status()}
    assert status["mock"] is True
    assert status["http"] is True
    assert status["home_assistant"] is False
    print("✓ Test 18 PASSED: provider status lists availability")


# 19
def test_iot_control_gated():
    from jarvis.tools import get_enhanced_registry

    reg = get_enhanced_registry()
    res = reg.execute("iot.control", device_id="missing", action="on")
    assert res.success is False
    assert res.meta.get("needs_confirmation") is True
    print("✓ Test 19 PASSED: iot.control is confirmation-gated")


# 20
def test_iot_tools_registered_and_permissions():
    from jarvis.tools import get_enhanced_registry

    names = {t["name"] for t in get_enhanced_registry().list_tools()}
    expected = {"iot.providers", "iot.devices", "iot.add_device", "iot.remove_device", "iot.status", "iot.control"}
    assert expected.issubset(names)
    assert len(get_iot_tools()) == 6
    pm = PermissionManager()
    assert pm.is_allowed("iot.read") and pm.is_allowed("iot.write")
    assert pm.needs_confirmation("iot.control") is True
    print("✓ Test 20 PASSED: iot tools registered + permission model")


# 21
def test_iot_registry_roundtrip():
    from jarvis.tools import get_enhanced_registry

    reg = get_enhanced_registry()
    added = reg.execute("iot.add_device", device_name="TestLamp", provider="mock")
    assert added.success, added.error
    did = added.result["id"]
    try:
        on = reg.execute("iot.control", device_id=did, action="on", confirm=True)
        assert on.success and on.result["state"]["power"] == "on"
        status = reg.execute("iot.status", device_id=did)
        assert status.success and status.result["power"] == "on"
        devices = reg.execute("iot.devices")
        assert devices.success and any(d["id"] == did for d in devices.result["devices"])
    finally:
        reg.execute("iot.remove_device", device_id=did)
    print("✓ Test 21 PASSED: iot tools roundtrip through the registry")


# 22
def test_iot_providers_tool():
    from jarvis.tools import get_enhanced_registry

    res = get_enhanced_registry().execute("iot.providers")
    assert res.success and len(res.result["providers"]) == 3
    print("✓ Test 22 PASSED: iot.providers tool")
