"""Phase 18 — Guided key setup + engine manager tests (offline).

Covers: service key storage/masking, engine validation/persistence, hardened
/settings endpoint, and the Settings UI wiring. No network, no live providers.
"""

import json

from fastapi.testclient import TestClient

from jarvis import db, engines, service_keys
from jarvis.app import app

SENSITIVE = ("secret.hf", "engine.llm", "provider.groq.api_key")


def client():
    return TestClient(app)


def _guard(*keys):
    """Snapshot settings so a test can restore exactly what it touched."""
    original = {k: db.get_setting(k) for k in keys}

    def restore():
        for k, v in original.items():
            if v is None:
                db.delete_setting(k)
            else:
                db.set_setting(k, v)

    return restore


# 1
def test_service_key_roundtrip_and_masking():
    restore = _guard("secret.hf")
    try:
        assert service_keys.is_known("hf") and service_keys.is_known("picovoice")
        assert not service_keys.is_known("nope")
        assert service_keys.set_key("nope", "x") is False

        assert service_keys.set_key("hf", "  hf_ABCDEFGH1234  ") is True
        assert service_keys.get_key("hf") == "hf_ABCDEFGH1234"

        st = service_keys.status("hf")
        assert st["key_set"] is True and st["key_hint"] == "…1234"
        assert "Hugging" in st["label"] and st["used_for"]
        # The raw secret must never appear in any client-safe payload.
        assert "hf_ABCDEFGH1234" not in json.dumps(service_keys.list_keys())

        assert service_keys.set_key("hf", "   ") is True  # empty clears
        assert service_keys.get_key("hf") is None
        assert service_keys.delete_key("nope") is False
    finally:
        restore()
    print("✓ Test 1 PASSED: service keys roundtrip, clear, and stay masked")


# 2
def test_engine_defaults_validation_and_set():
    restore = _guard("engine.llm")
    try:
        db.delete_setting("engine.llm")
        assert engines.get("llm") == "auto"  # default when unset

        assert engines.valid("llm", "bogus") is False
        assert engines.set("llm", "bogus") is False
        assert engines.get("llm") == "auto"  # rejected value never stored

        assert engines.set("llm", "on_device") is True
        assert engines.get("llm") == "on_device"
        assert engines.set("unknown_component", "auto") is False

        snap = engines.snapshot()
        assert set(snap) == {"llm", "stt", "image"}
        assert snap["llm"]["value"] == "on_device"
        for spec in snap.values():
            assert spec["default"] in [o["value"] for o in spec["options"]]
            assert spec["value"] in [o["value"] for o in spec["options"]]
    finally:
        restore()
    print("✓ Test 2 PASSED: engine choices validate, persist, and default safely")


# 3
def test_api_keys_endpoint_masked_and_roundtrip():
    restore = _guard("secret.picovoice")
    try:
        with client() as c:
            r = c.get("/api/keys")
            assert r.status_code == 200
            listed = r.json()["keys"]
            names = {k["name"] for k in listed}
            assert {"hf", "picovoice"} <= names
            for k in listed:
                for field in ("label", "hint", "used_for", "key_set", "key_hint"):
                    assert field in k

            # save
            r = c.post("/api/keys/picovoice", json={"api_key": "pv_SECRETVALUE99"})
            assert r.status_code == 200
            assert r.json()["key"]["key_set"] is True
            assert "pv_SECRETVALUE99" not in r.text
            # the raw secret never leaks via keys or settings reads
            assert "pv_SECRETVALUE99" not in c.get("/api/keys").text
            assert "pv_SECRETVALUE99" not in c.get("/api/settings").text

            # unknown name -> 404; empty body is a no-op
            assert c.post("/api/keys/nope", json={"api_key": "x"}).status_code == 404
            assert c.post("/api/keys/picovoice", json={}).status_code == 200

            # clear
            r = c.post("/api/keys/picovoice", json={"clear_key": True})
            assert r.status_code == 200
            assert r.json()["key"]["key_set"] is False
    finally:
        restore()
    print("✓ Test 3 PASSED: /api/keys saves, masks, clears, and 404s unknowns")


# 4
def test_api_engines_roundtrip_and_validation():
    restore = _guard("engine.llm", "engine.stt", "engine.image")
    try:
        with client() as c:
            r = c.get("/api/engines")
            assert r.status_code == 200
            eng = r.json()["engines"]
            assert set(eng) == {"llm", "stt", "image"}
            for spec in eng.values():
                for field in ("label", "description", "value", "default", "options"):
                    assert field in spec

            # invalid -> 400, nothing stored
            r = c.post("/api/engines", json={"llm": "bogus"})
            assert r.status_code == 400
            assert "invalid" in r.json()["error"]

            # valid roundtrip
            r = c.post("/api/engines", json={"llm": "on_device", "image": "local"})
            assert r.status_code == 200 and r.json()["ok"] is True
            assert c.get("/api/engines").json()["engines"]["llm"]["value"] == "on_device"

            # partial update leaves the other components alone
            r = c.post("/api/engines", json={"stt": "cloud"})
            assert r.status_code == 200
            assert r.json()["engines"]["llm"]["value"] == "on_device"
            assert r.json()["engines"]["stt"]["value"] == "cloud"
    finally:
        restore()
    print("✓ Test 4 PASSED: /api/engines validates, roundtrips, updates partially")


# 5
def test_settings_endpoint_hides_sensitive_prefixes():
    restore = _guard(*SENSITIVE)
    marker = "phase18.marker"
    before = {k: db.get_setting(k) for k in SENSITIVE}
    try:
        with client() as c:
            r = c.post(
                "/api/settings",
                json={
                    marker: "ok",
                    "secret.hf": "INJECTED_SECRET",
                    "engine.llm": "on_device",
                    "provider.groq.api_key": "INJECTED_KEY",
                },
            )
            assert r.status_code == 200 and r.json()["ok"] is True

            body = c.get("/api/settings").json()
            assert body.get(marker) == "ok"
            assert "secret.hf" not in body
            assert "engine.llm" not in body
            assert "provider.groq.api_key" not in body
            assert not any(k.startswith(("secret.", "engine.", "provider.")) for k in body)

        # the generic endpoint could not write any protected value
        for k in SENSITIVE:
            assert db.get_setting(k) == before[k], f"leak or clobber via /api/settings: {k}"
    finally:
        db.delete_setting(marker)
        restore()
    print("✓ Test 5 PASSED: /api/settings hides and refuses provider/secret/engine keys")


# 6
def test_settings_ui_exposes_setup_keys_and_engines():
    with client() as c:
        html = c.get("/").text
        for needle in ("setup-checklist", "service-keys-list", "engines-list", "save-engines"):
            assert needle in html, f"missing {needle}"
        js = c.get("/static/app.js").text
        assert "/api/keys" in js and "/api/engines" in js
        assert "loadServiceKeys" in js and "renderSetup" in js
        css = c.get("/static/style.css").text
        assert ".checklist" in css
    print("✓ Test 6 PASSED: Settings UI ships checklist, service keys and engine controls")
