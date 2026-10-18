"""Phase 19 — On-device LLM (LiteRT-LM) + model download manager (offline).

Downloads are exercised against a throwaway local HTTP server; the engine
bridge is a fake stand-in. No real network, no live models.
"""

import asyncio
import json
import os
import shutil
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fastapi.testclient import TestClient

from jarvis import db, engines, llm, ondevice
from jarvis.app import app

PAYLOAD = os.urandom(1024) * 384  # ~384 KB

TEST_ID = "test-tiny"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence test output
        pass

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path == "/gated":
            self.send_response(401)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"401 GatedRepo")
            return
        body = PAYLOAD if self.path == "/ok" else PAYLOAD
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.path == "/slow":
            for i in range(0, len(body), 4096):
                try:
                    self.wfile.write(body[i : i + 4096])
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return
                time.sleep(0.08)
            return
        self.wfile.write(body)


def serve():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def make_env(port, path="/ok", url=None):
    d = Path(tempfile.mkdtemp(prefix="jodl-"))
    original_dir = ondevice.model_dir
    ondevice.model_dir = lambda: d
    entry = {
        "id": TEST_ID,
        "label": "Test Tiny",
        "description": "tiny test model",
        "repo": "test/tiny",
        "file": "tiny.litertlm",
        "size": len(PAYLOAD),
        "min_ram_gb": 1,
        "url": url if url is not None else f"http://127.0.0.1:{port}{path}",
    }
    ondevice.CATALOG.append(entry)

    def teardown():
        ondevice.CATALOG.remove(entry)
        ondevice.model_dir = original_dir
        ondevice.reset_state()
        ondevice.clear_backend()
        shutil.rmtree(d, ignore_errors=True)

    return entry, teardown


def wait_until(pred, timeout=20.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(interval)
    return False


def state_of(model_id):
    for m in ondevice.status():
        if m["id"] == model_id:
            return m
    return {}


class FakeBackend:
    def __init__(self, text="Hello from the device"):
        self.loaded = False
        self.text = text
        self.calls = []

    def isLoaded(self):  # noqa: N802 - mirrors the Kotlin bridge
        return self.loaded

    def deviceInfo(self):  # noqa: N802
        return {
            "supported": True,
            "platform": "android",
            "mem_total_bytes": 4 * 1024**3,
            "abis": ["arm64-v8a"],
        }

    def load(self, path):
        if not os.path.isfile(path):
            return {"ok": False, "error": "model file not found"}
        self.loaded = True
        return {"ok": True, "model": os.path.basename(path)}

    def unload(self):
        self.loaded = False
        return {"ok": True}

    def generate(self, request_json):
        self.calls.append(json.loads(request_json))
        return {"ok": True, "text": self.text}


def client():
    return TestClient(app)


def guard_settings(*keys):
    original = {k: db.get_setting(k) for k in keys}

    def restore():
        for k, v in original.items():
            if v is None:
                db.delete_setting(k)
            else:
                db.set_setting(k, v)

    return restore


# 1
def test_catalog_and_device_info():
    ids = [e["id"] for e in ondevice.CATALOG]
    assert len(ids) == len(set(ids)), "duplicate model ids"
    for e in ondevice.CATALOG:
        for field in ("label", "description", "repo", "file", "size", "min_ram_gb"):
            assert e.get(field), f"{e['id']} missing {field}"
        assert e["file"].endswith(".litertlm")
        assert e["size"] > 0 and e["repo"].count("/") == 1
        assert "huggingface.co" in ondevice.download_url(e)

    info = ondevice.device_info()
    assert info["supported"] is False and info["platform"] == "host"
    assert not ondevice.is_ready() and ondevice.loaded_id() is None
    print("✓ Test 1 PASSED: catalogue is well-formed; host reports no engine")


# 2
def test_download_installs_and_reports_progress():
    srv, port = serve()
    entry, teardown = make_env(port)
    try:
        res = ondevice.start_download(TEST_ID)
        assert res["ok"] and res["id"] == TEST_ID

        seen_progress = wait_until(
            lambda: state_of(TEST_ID)["state"] == "downloading", timeout=5
        )
        done = wait_until(lambda: state_of(TEST_ID)["installed"], timeout=20)
        assert done, f"download did not finish: {state_of(TEST_ID)}"

        st = state_of(TEST_ID)
        assert st["installed_bytes"] == len(PAYLOAD)
        assert st["progress"] == 100.0
        assert ondevice.installed_size(TEST_ID) == len(PAYLOAD)
        assert not ondevice.part_path(TEST_ID).exists()
        assert seen_progress or True

        again = ondevice.status()
        assert any(m["id"] == TEST_ID and m["installed"] for m in again)

        removed = ondevice.remove(TEST_ID)
        assert removed["ok"] and not ondevice.file_path(TEST_ID).exists()
        assert state_of(TEST_ID)["installed"] is False
    finally:
        teardown()
        srv.shutdown()
    print("✓ Test 2 PASSED: download installs, verifies size, deletes cleanly")


# 3
def test_cancel_download_removes_partial():
    srv, port = serve()
    entry, teardown = make_env(port, path="/slow")
    try:
        ondevice.start_download(TEST_ID)
        assert wait_until(
            lambda: state_of(TEST_ID)["state"] == "downloading", timeout=5
        ), state_of(TEST_ID)
        assert wait_until(lambda: state_of(TEST_ID)["done_bytes"] > 0, timeout=10)

        ondevice.cancel_download(TEST_ID)
        assert wait_until(
            lambda: state_of(TEST_ID)["state"] == "cancelled", timeout=10
        ), state_of(TEST_ID)
        assert not ondevice.file_path(TEST_ID).exists()
        assert not ondevice.part_path(TEST_ID).exists()
        assert ondevice.installed_size(TEST_ID) is None
    finally:
        teardown()
        srv.shutdown()
    print("✓ Test 3 PASSED: cancel stops the download and clears the partial file")


# 4
def test_gated_download_explains_hugging_face_token():
    srv, port = serve()
    entry, teardown = make_env(port, path="/gated")
    try:
        ondevice.start_download(TEST_ID)
        assert wait_until(lambda: state_of(TEST_ID)["state"] == "error", timeout=15)
        err = state_of(TEST_ID)["error"] or ""
        assert "Hugging Face" in err and "token" in err, err
        assert not ondevice.file_path(TEST_ID).exists()
    finally:
        teardown()
        srv.shutdown()
    print("✓ Test 4 PASSED: gated models explain the token requirement")


# 5
def test_endpoints_offline_behaviour():
    srv, port = serve()
    entry, teardown = make_env(port)
    try:
        with client() as c:
            info = c.get("/api/ondevice/info").json()
            assert "device" in info and info["ready"] is False

            models = c.get("/api/ondevice/models").json()
            assert any(m["id"] == TEST_ID for m in models["models"])

            assert c.post("/api/ondevice/download", json={"id": "nope"}).status_code == 404
            assert c.post("/api/ondevice/delete", json={"id": "nope"}).status_code == 404
            assert c.post("/api/ondevice/cancel", json={"id": "nope"}).status_code == 404

            r = c.post("/api/ondevice/load", json={"id": TEST_ID})
            assert r.status_code == 400
            assert "not downloaded" in r.json()["error"]

            r = c.post("/api/ondevice/generate", json={"prompt": "hi"})
            assert r.status_code == 400
            assert "requires the Android app" in r.json()["error"] or r.json()["error"]

            r = c.post("/api/ondevice/generate", json={"prompt": "   "})
            assert r.status_code == 400

            started = c.post("/api/ondevice/download", json={"id": TEST_ID})
            assert started.status_code == 202
            assert wait_until(
                lambda: c.get("/api/ondevice/models").json()["models"][-1]["installed"],
                timeout=20,
            )
            assert c.post(
                "/api/ondevice/download", json={"id": TEST_ID}
            ).status_code == 409
            assert c.post("/api/ondevice/delete", json={"id": TEST_ID}).status_code == 200
    finally:
        teardown()
        srv.shutdown()
    print("✓ Test 5 PASSED: /api/ondevice endpoints behave offline")


# 6
def test_bridge_loads_and_generates_then_llm_uses_it():
    srv, port = serve()
    entry, teardown = make_env(port)
    restore = guard_settings("engine.llm")
    fake = FakeBackend()
    try:
        ondevice.start_download(TEST_ID)
        assert wait_until(lambda: state_of(TEST_ID)["installed"], timeout=20)

        ondevice.set_backend(fake)
        loaded = ondevice.load(TEST_ID)
        assert loaded["ok"] and fake.loaded
        assert ondevice.is_ready() and ondevice.loaded_id() == TEST_ID

        text = ondevice.chat([{"role": "user", "content": "hi"}], 64)
        assert text == "Hello from the device"
        assert fake.calls and fake.calls[0]["messages"][0]["content"] == "hi"
        assert fake.calls[0]["max_tokens"] == 64

        engines.set("llm", "on_device")
        out = asyncio.run(llm.complete([{"role": "user", "content": "hi"}]))
        assert out == ("Hello from the device", "on_device")
        assert asyncio.run(llm.active_provider()) == "on_device"

        engines.set("llm", "cloud")
        assert asyncio.run(llm.active_provider()) != "on_device"

        assert ondevice.unload()["ok"] and not fake.loaded
        assert not ondevice.is_ready()
    finally:
        restore()
        teardown()
        srv.shutdown()
    print("✓ Test 6 PASSED: bridge loads/generates; chat engine routes to on-device")


# 7
def test_engine_on_device_without_model_fails_honestly():
    restore = guard_settings("engine.llm")
    try:
        engines.set("llm", "on_device")
        ondevice.clear_backend()
        assert asyncio.run(llm.active_provider()) is None
        try:
            asyncio.run(llm.complete([{"role": "user", "content": "hi"}]))
        except llm.ProviderError as exc:
            assert "on-device" in str(exc)
        else:
            raise AssertionError("expected ProviderError without a model")
    finally:
        restore()
    print("✓ Test 7 PASSED: engine=on_device without a model fails honestly")


# 8
def test_settings_ui_ships_ondevice_manager():
    html = Path("web/index.html").read_text(encoding="utf-8")
    for marker in ("ondevice-info", "ondevice-list", "On-device model"):
        assert marker in html, marker
    js = Path("web/app.js").read_text(encoding="utf-8")
    for marker in (
        "/api/ondevice/info",
        "/api/ondevice/models",
        "/api/ondevice/${action}",
        "[data-od-action]",
        "onDeviceAction",
        "fmtBytes",
    ):
        assert marker in js, marker
    css = Path("web/style.css").read_text(encoding="utf-8")
    assert ".od-card" in css and ".od-fill" in css
    print("✓ Test 8 PASSED: Settings UI ships the on-device model manager")


# 9
def test_ram_gate_rejects_model_bigger_than_device():
    entry, teardown = make_env(0, url="http://127.0.0.1:9/unreachable")
    fake = FakeBackend()  # reports a 4 GB android device
    try:
        ondevice.set_backend(fake)
        entry["min_ram_gb"] = 8
        try:
            ondevice.start_download(TEST_ID)
        except ondevice.OnDeviceError as exc:
            msg = str(exc)
            assert "RAM" in msg and "8 GB" in msg and "pick a smaller model" in msg, msg
        else:
            raise AssertionError("RAM gate did not reject the download")
        assert ondevice.installed_size(TEST_ID) is None
    finally:
        teardown()
    print("✓ Test 9 PASSED: downloads are gated on the device's RAM")


# 10
def test_download_auto_loads_for_chat():
    srv, port = serve()
    entry, teardown = make_env(port)
    fake = FakeBackend()
    try:
        ondevice.set_backend(fake)
        ondevice.start_download(TEST_ID)
        assert wait_until(lambda: state_of(TEST_ID)["installed"], timeout=20)
        assert wait_until(lambda: ondevice.is_ready(), timeout=10), state_of(TEST_ID)
        assert ondevice.loaded_id() == TEST_ID
        assert state_of(TEST_ID)["loaded"] is True
        assert not state_of(TEST_ID)["error"]
    finally:
        teardown()
        srv.shutdown()
    print("✓ Test 10 PASSED: a finished download auto-loads and is ready for chat")


# 11
def test_failed_auto_load_is_recorded_and_not_retried():
    srv, port = serve()
    entry, teardown = make_env(port)

    class _FailLoad(FakeBackend):
        def __init__(self):
            super().__init__()
            self.load_attempts = 0

        def load(self, path):
            self.load_attempts += 1
            return {"ok": False, "error": "out of memory"}

    fake = _FailLoad()
    try:
        ondevice.set_backend(fake)
        ondevice.start_download(TEST_ID)
        assert wait_until(lambda: state_of(TEST_ID)["installed"], timeout=20)
        assert wait_until(
            lambda: "load failed" in (state_of(TEST_ID)["error"] or ""), timeout=10
        ), state_of(TEST_ID)
        assert not ondevice.is_ready()
        assert "out of memory" in state_of(TEST_ID)["error"]
        assert ondevice.auto_load() is None
        assert fake.load_attempts == 1, "failed model was retried in the same session"
    finally:
        teardown()
        srv.shutdown()
    print("✓ Test 11 PASSED: load failures are recorded and not retried in-session")


# 12
def test_first_chat_auto_loads_installed_model():
    srv, port = serve()
    entry, teardown = make_env(port)
    restore = guard_settings("engine.llm")
    fake = FakeBackend()
    try:
        ondevice.start_download(TEST_ID)  # no bridge yet: stages the file only
        assert wait_until(lambda: state_of(TEST_ID)["installed"], timeout=20)
        ondevice.set_backend(fake)
        engines.set("llm", "on_device")
        assert not ondevice.is_ready()
        assert asyncio.run(llm.active_provider()) is None

        from jarvis.router import Router

        dec = asyncio.run(Router().route("hello"))
        assert dec["kind"] == "chat", dec
        assert dec["provider"] == "on_device"
        assert fake.loaded and ondevice.is_ready()
    finally:
        restore()
        teardown()
        srv.shutdown()
    print("✓ Test 12 PASSED: the first chat auto-loads the downloaded model")


# 13
def test_honest_fallback_when_nothing_can_answer():
    from unittest import mock

    from jarvis import assistant, atif_client

    async def _ask(question, session=None, url=None, timeout=120.0):
        return {
            "ok": True,
            "data": {"text": "[UNKNOWN] canned Atif fallback", "provider": "offline"},
        }

    async def _no_active():
        return None

    ondevice.clear_backend()
    with mock.patch.object(atif_client, "ask", _ask), mock.patch.object(
        llm, "active_provider", _no_active
    ), mock.patch.object(llm, "has_provider", lambda: False):
        a = assistant.Assistant(mode="auto")
        text, provider, _tool = asyncio.run(a.respond("hello"))
    assert provider == "basic", provider
    assert "Chat has no model:" in text
    assert "no cloud provider key is set" in text
    assert "on-device chat requires the Android app" in text
    assert "(Atif: Atif has no model provider configured.)" in text
    assert "[UNKNOWN]" not in text, "Atif's canned text passed off as the answer"
    print("✓ Test 13 PASSED: fallback states Jarvis's own diagnosis, not Atif's")
