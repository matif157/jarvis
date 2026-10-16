"""Phase 12 API + Web UI Tests (offline; no network, no live providers)."""

from pathlib import Path

from fastapi.testclient import TestClient

from jarvis import db
from jarvis.app import app
from jarvis.tools import get_enhanced_registry

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def client():
    return TestClient(app)


# 1
def test_health_no_probe_is_offline_safe():
    with client() as c:
        r = c.get("/api/health", params={"probe": "false"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["app"] == "jarvis"
        assert body["providers"] == []
        assert isinstance(body["has_provider"], bool)
    print("✓ Test 1 PASSED: /api/health (probe=false) is offline-safe")


# 2
def test_status_reports_tools_and_subsystems():
    with client() as c:
        body = c.get("/api/status").json()
        assert body["ok"] is True
        assert body["tools"] == len(get_enhanced_registry().list_tools())
        assert body["tools"] >= 51
        assert "tts" in body["voice"] and "stt" in body["voice"]
        assert "host" in body and "port" in body
    print("✓ Test 2 PASSED: /api/status reports tool count and subsystems")


# 3
def test_tools_listing_exposes_phase_tools():
    with client() as c:
        body = c.get("/api/tools").json()
        assert body["count"] == len(get_enhanced_registry().list_tools())
        names = {t["name"] for t in body["tools"]}
        for expected in ("echo", "time.now", "job.search", "voice.speak", "application.add"):
            assert expected in names, f"missing {expected}"
        sample = next(t for t in body["tools"] if t["name"] == "voice.listen")
        assert "voice.listen" in sample["permissions"]
    print("✓ Test 3 PASSED: /api/tools lists phase tools with permissions")


# 4
def test_run_tool_echo_roundtrip():
    with client() as c:
        r = c.post("/api/tools/echo", json={"params": {"text": "hello jarvis"}})
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["result"] == "hello jarvis"
    print("✓ Test 4 PASSED: POST /api/tools/echo executes a tool")


# 5
def test_run_unknown_tool_is_404():
    with client() as c:
        r = c.post("/api/tools/does.not.exist", json={"params": {}})
        assert r.status_code == 404
        assert r.json()["success"] is False
        assert "unknown tool" in r.json()["error"]
    print("✓ Test 5 PASSED: unknown tool returns 404")


# 6
def test_gated_tool_requires_confirmation():
    with client() as c:
        r = c.post("/api/tools/voice.listen", json={"params": {}, "confirm": False})
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is False
        assert body["meta"].get("needs_confirmation") is True
    print("✓ Test 6 PASSED: gated tool without confirm reports needs_confirmation")


# 7
def test_gated_tool_with_confirm_runs():
    with client() as c:
        r = c.post("/api/tools/voice.listen", json={"params": {}, "confirm": True})
        assert r.status_code == 200
        body = r.json()
        # Offline: no STT backend installed, but the gate is passed.
        assert body["success"] is False
        assert body["meta"].get("needs_confirmation") is not True
    print("✓ Test 7 PASSED: gated tool with confirm passes the gate")


# 8
def test_chat_basic_mode_offline():
    with client() as c:
        r = c.post("/api/chat", json={"message": "hello", "mode": "basic"})
        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "basic"
        assert isinstance(body["text"], str) and body["text"].strip()
        assert "session" in body
    print("✓ Test 8 PASSED: /api/chat basic mode answers offline")


# 9
def test_settings_roundtrip_non_provider_only():
    key = "test.phase12"
    with client() as c:
        r = c.post("/api/settings", json={key: "abc123"})
        assert r.status_code == 200 and r.json()["ok"] is True
        assert c.get("/api/settings").json().get(key) == "abc123"
        # Provider-prefixed keys must be ignored by the settings endpoint.
        c.post("/api/settings", json={"provider.groq.api_key": "leak"})
        assert "provider.groq.api_key" not in c.get("/api/settings").json()
    db.delete_setting(key)
    print("✓ Test 9 PASSED: /api/settings roundtrips and blocks provider keys")


# 10
def test_providers_endpoint_structure():
    with client() as c:
        body = c.get("/api/providers").json()
        names = [p["name"] for p in body["providers"]]
        assert "ollama" in names
        assert body["order"] == names
        first = body["providers"][0]
        for field in ("name", "label", "key_set", "ready"):
            assert field in first
    print("✓ Test 10 PASSED: /api/providers returns ordered provider list")


# 11
def test_index_page_served_with_tabs():
    with client() as c:
        r = c.get("/")
        assert r.status_code == 200
        html = r.text
        assert "JARVIS" in html
        for tab in ("Chat", "Tools", "Settings"):
            assert tab in html
    print("✓ Test 11 PASSED: index page served with Chat/Tools/Settings tabs")


# 12
def test_static_assets_served():
    with client() as c:
        js = c.get("/static/app.js")
        css = c.get("/static/style.css")
        assert js.status_code == 200 and "api/chat" in js.text
        assert css.status_code == 200 and ".chat-log" in css.text
    print("✓ Test 12 PASSED: static JS/CSS served and include chat UI")
