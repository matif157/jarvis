"""Phase 20 — Voice: Android TTS, speech-to-text (on-device + cloud) and the
Porcupine wake word (offline).

The Java bridges are replaced by fakes that mirror their JSON-in/JSON-out
static API, and the cloud STT path is exercised against a throwaway local
HTTP server. No real network, no microphone, no models.
"""

import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fastapi.testclient import TestClient

from jarvis import db, engines, llm, service_keys, voice
from jarvis.app import app

GROQ_KEY = "provider.groq.api_key"
PICOVOICE_KEY = "secret.picovoice"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeVoiceBridge:
    """Mirrors ai.jarvis.assistant.voice.VoiceBridge (static methods)."""

    def __init__(self):
        self.spoken = []
        self.records = []
        self.status_calls = 0
        self.text = "hello from speech"
        self.voices_list = ["ur-PK-local", "en-US-local"]
        self.fail_speak = None
        self.fail_recognize = None
        self.fail_record = None
        self.path = None

    def speak(self, request_json):
        if self.fail_speak:
            return {"ok": False, "error": self.fail_speak}
        self.spoken.append(json.loads(request_json))
        return {"ok": True, "provider": "android_tts"}

    def stopSpeak(self):
        return {"ok": True}

    def voices(self, request_json):
        return {"ok": True, "voices": list(self.voices_list)}

    def status(self):
        self.status_calls += 1
        return {
            "ok": True,
            "tts": {"ready": True, "initialised": True, "speaking": False},
            "mic": {"granted": True},
        }

    def recognize(self, request_json):
        if self.fail_recognize:
            return {"ok": False, "error": self.fail_recognize}
        return {"ok": True, "text": self.text}

    def record(self, request_json):
        if self.fail_record:
            return {"ok": False, "error": self.fail_record}
        request = json.loads(request_json)
        self.records.append(request)
        return {"ok": True, "path": self.path, "seconds": request.get("seconds")}


class FakeWakeBridge:
    """Mirrors ai.jarvis.assistant.voice.WakeBridge (static methods)."""

    def __init__(self):
        self.running = False
        self.keyword = None
        self.calls = []

    def start(self, request_json):
        request = json.loads(request_json)
        self.calls.append(request)
        if not request.get("access_key"):
            return {"ok": False, "error": "access key required"}
        self.running = True
        self.keyword = request.get("keyword")
        return {"ok": True, "keyword": self.keyword}

    def stop(self):
        self.running = False
        return {"ok": True}

    def status(self):
        return {
            "ok": True,
            "supported": True,
            "running": self.running,
            "keyword": self.keyword or "",
            "mic_granted": True,
        }

    def keywords(self):
        return {"ok": True, "keywords": ["jarvis", "computer"]}


class _SttHandler(BaseHTTPRequestHandler):
    """Minimal Groq-compatible transcription endpoint."""

    def log_message(self, *args):  # silence test output
        pass

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        if "error" in self.path:
            payload = b'{"error": {"message": "bad key"}}'
            code = 401
        else:
            assert b"RIFF" in body or b"fake" in body or body, "no audio uploaded"
            assert self.headers.get("Authorization") == "Bearer test-groq-key"
            payload = json.dumps({"text": "  urdu transcript  "}).encode()
            code = 200
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def serve():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _SttHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


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


def temp_wav(name="sample.wav", data=b"RIFFfake-audio"):
    """A WAV inside the repo (one of the safe bases) so path checks pass."""
    d = tempfile.TemporaryDirectory(prefix="jv20-", dir=".")
    p = Path(d.name) / name
    p.write_bytes(data)
    return p, d


# 1
def test_status_payload_shape_offline():
    voice.clear_backend()
    data = voice.status_payload()
    assert data["ok"] is True and data["android"] is False
    assert data["tts"]["available"] is True  # say or mock on any machine
    assert data["tts"]["provider"] in {"macos_say", "mock"}
    assert data["stt"]["available"] is False
    assert data["stt_engine"] in {"on_device", "cloud", "auto"}
    assert data["wake"] == {"supported": False}
    assert data["wake_key_set"] is False
    assert data["wake_keywords"] == []
    assert "device" not in data

    assert voice.is_android() is False
    assert voice.android_status() == {"supported": False}
    assert voice.list_voices() == []
    assert voice.wake_keywords() == []
    print("✓ Test 1 PASSED: offline status payload is honest and complete")


# 2
def test_bridge_speak_voices_and_manager_prefers_android():
    fake = FakeVoiceBridge()
    voice.set_backend(voice=fake)
    try:
        assert voice.is_android() is True

        out = voice.speak_text("salam", language="ur-PK", rate=200)
        assert out["provider"] == "android_tts"
        assert fake.spoken[0]["text"] == "salam"
        assert fake.spoken[0]["language"] == "ur-PK"
        # wpm-style rate is converted to a speech-rate multiplier
        assert 1.0 < fake.spoken[0]["rate"] < 1.2

        voice.speak_text("no rate")
        assert "rate" not in fake.spoken[1]

        assert voice.list_voices() == ["ur-PK-local", "en-US-local"]
        voice.stop_speech()

        manager = voice.VoiceManager()
        assert manager.tts.name == "android_tts"
        assert manager.stt.name == "android_speech"
        status = manager.status()
        assert status["tts"]["provider"] == "android_tts"
        assert status["tts"]["voice_count"] == 2
        assert status["stt"] == {"provider": "android_speech", "available": True}

        ok, message = manager.speak("hi")
        assert ok and message == "spoken"
        ok, text = manager.listen()
        assert ok and text == "hello from speech"
    finally:
        voice.clear_backend()
    assert voice.is_android() is False
    print("✓ Test 2 PASSED: bridge speak/voices work; manager prefers Android")


# 3
def test_bridge_error_paths_surface_messages():
    fake = FakeVoiceBridge()
    voice.set_backend(voice=fake)
    try:
        fake.fail_recognize = "microphone permission not granted"
        try:
            voice.recognize_speech()
        except voice.VoiceError as exc:
            assert "permission" in str(exc)
        else:
            raise AssertionError("expected VoiceError")

        fake.fail_recognize = None
        fake.text = "   "
        try:
            voice.recognize_speech()
        except voice.VoiceError as exc:
            assert "nothing recognized" in str(exc)
        else:
            raise AssertionError("expected VoiceError for empty speech")

        fake.text = "ok now"
        assert voice.recognize_speech(language="ur-PK", timeout_ms=15000) == "ok now"

        fake.fail_speak = "text-to-speech is not initialised"
        ok, message = voice.AndroidTTS().speak("hi")
        assert ok is False and "not initialised" in message

        fake.fail_record = "audio recording is not supported on this device"
        try:
            voice.record_wav()
        except voice.VoiceError as exc:
            assert "not supported" in str(exc)
        else:
            raise AssertionError("expected VoiceError")

        assert voice.AndroidSTT().transcribe("some.wav") == (
            False,
            "on-device recognition needs live audio; "
            "transcribe files with a cloud STT key",
        )
    finally:
        voice.clear_backend()
    print("✓ Test 3 PASSED: bridge errors surface as clear messages")


# 4
def test_endpoints_speak_stop_voices_and_permission_mapping():
    fake = FakeVoiceBridge()
    voice.set_backend(voice=fake)
    try:
        with client() as c:
            data = c.get("/api/voice/status").json()
            assert data["ok"] and data["android"] is True
            assert data["device"]["supported"] is True
            assert data["tts"]["provider"] == "android_tts"

            r = c.post("/api/voice/speak", json={"text": "  "})
            assert r.status_code == 400

            r = c.post("/api/voice/speak", json={"text": "hello", "rate": 1.0})
            assert r.status_code == 200 and r.json()["provider"] == "android_tts"
            assert fake.spoken[-1]["text"] == "hello"

            assert c.post("/api/voice/stop").json() == {"ok": True}

            voices = c.get("/api/voice/voices").json()
            assert voices["count"] == 2 and voices["provider"] == "android_tts"

            fake.fail_recognize = "microphone permission not granted"
            engines.set("stt", "on_device")
            r = c.post("/api/voice/transcribe", json={})
            assert r.status_code == 403, r.json()
            assert "permission" in r.json()["error"]

            fake.fail_recognize = "speech recognition failed (code 7)"
            r = c.post("/api/voice/transcribe", json={})
            assert r.status_code == 400 and "code 7" in r.json()["error"]
    finally:
        voice.clear_backend()
        restore = guard_settings("engine.stt")
        restore()
    print("✓ Test 4 PASSED: voice endpoints + permission mapping behave")


# 5
def test_transcribe_live_engine_routing():
    fake = FakeVoiceBridge()
    restore_engine = guard_settings("engine.stt")
    srv, port = serve()
    original_url = voice.CLOUD_STT_URL
    voice.set_backend(voice=fake)
    voice.CLOUD_STT_URL = f"http://127.0.0.1:{port}/openai/v1/audio/transcriptions"
    restore_key = guard_settings(GROQ_KEY)
    db.set_setting(GROQ_KEY, "test-groq-key")
    try:
        # on_device → platform recognizer, no recording
        fake.text = "platform heard me"
        engines.set("stt", "on_device")
        ok, text, provider = voice.transcribe_live()
        assert (ok, text, provider) == (True, "platform heard me", "android_speech")
        assert fake.records == []

        # cloud → record then upload
        wav, folder = temp_wav()
        fake.path = str(wav)
        engines.set("stt", "cloud")
        ok, text, provider = voice.transcribe_live(seconds=3)
        assert ok and text == "urdu transcript" and provider == "groq_whisper"
        assert fake.records and fake.records[0]["seconds"] == 3

        # auto → on-device fails, cloud fallback succeeds
        fake.fail_recognize = "speech recognition failed (code 10)"
        engines.set("stt", "auto")
        ok, text, provider = voice.transcribe_live()
        assert ok and text == "urdu transcript" and provider == "groq_whisper"

        # on_device still refuses to fall back
        engines.set("stt", "on_device")
        ok, text, provider = voice.transcribe_live()
        assert not ok and "code 10" in text and provider == "android_speech"

        # cloud without a recording device
        fake.fail_record = "cannot open microphone"
        engines.set("stt", "cloud")
        ok, text, provider = voice.transcribe_live()
        assert not ok and "cannot open microphone" in text
        folder.cleanup()
    finally:
        voice.CLOUD_STT_URL = original_url
        voice.clear_backend()
        restore_engine()
        restore_key()
        srv.shutdown()
    print("✓ Test 5 PASSED: engine.stt routes live transcription correctly")


# 6
def test_transcribe_file_prefers_installed_backend_then_cloud():
    srv, port = serve()
    original_url = voice.CLOUD_STT_URL
    voice.set_backend(voice=FakeVoiceBridge())
    voice.CLOUD_STT_URL = f"http://127.0.0.1:{port}/openai/v1/audio/transcriptions"
    restore_key = guard_settings(GROQ_KEY)
    db.set_setting(GROQ_KEY, "test-groq-key")
    wav, folder = temp_wav()
    try:
        # Desktop has no whisper/speech_recognition here → cloud takes over.
        ok, text, provider = voice.transcribe_file(str(wav))
        assert ok and text == "urdu transcript" and provider == "groq_whisper"
        assert voice.AndroidSTT().transcribe(None)[1] == "hello from speech"

        missing = Path(folder.name) / "nope.wav"
        ok, text, provider = voice.transcribe_file(str(missing))
        assert not ok and "not found" in text

        outside = Path(tempfile.gettempdir()) / "jv20-outside.wav"
        outside.write_bytes(b"RIFFfake")
        ok, text, provider = voice.transcribe_file(str(outside))
        assert not ok and "not allowed" in text
        outside.unlink()

        with client() as c:
            r = c.post("/api/voice/transcribe", json={"audio_path": str(missing)})
            assert r.status_code == 400 and "not found" in r.json()["error"]
    finally:
        voice.CLOUD_STT_URL = original_url
        voice.clear_backend()
        restore_key()
        folder.cleanup()
        srv.shutdown()
    print("✓ Test 6 PASSED: file transcription falls back to cloud safely")


# 7
def test_cloud_transcribe_requires_groq_key():
    restore = guard_settings(GROQ_KEY)
    db.delete_setting(GROQ_KEY)
    original = os.environ.pop("GROQ_API_KEY", None)
    wav, folder = temp_wav()
    try:
        ok, message = voice.cloud_transcribe(str(wav))
        assert not ok and "Groq API key" in message
    finally:
        if original is not None:
            os.environ["GROQ_API_KEY"] = original
        restore()
        folder.cleanup()
    print("✓ Test 7 PASSED: cloud STT asks for a Groq key instead of failing")


# 8
def test_wake_word_endpoints_and_prerequisites():
    wake = FakeWakeBridge()
    restore_key = guard_settings(PICOVOICE_KEY, "engine.stt")
    db.delete_setting(PICOVOICE_KEY)
    voice.set_backend(voice=FakeVoiceBridge(), wake=wake)
    try:
        with client() as c:
            status = c.get("/api/wake/status").json()
            assert status["supported"] and status["running"] is False
            assert status["key_set"] is False
            assert status["keywords"] == ["jarvis", "computer"]

            r = c.post("/api/wake/start", json={"keyword": "jarvis"})
            assert r.status_code == 409 and "access key" in r.json()["error"]

            service_keys.set_key("picovoice", "pv-test-key")
            r = c.post("/api/wake/start", json={"keyword": "computer"})
            assert r.status_code == 200 and r.json()["keyword"] == "computer"
            assert wake.calls[-1]["access_key"] == "pv-test-key"

            status = c.get("/api/wake/status").json()
            assert status["key_set"] is True and status["running"] is True
            assert status["keyword"] == "computer"

            assert c.post("/api/wake/stop").json() == {"ok": True}
            assert wake.running is False
            assert c.get("/api/wake/status").json()["running"] is False

            # the status payload also carries the wake state
            payload = c.get("/api/voice/status").json()
            assert payload["wake_key_set"] is True
            assert payload["wake"]["supported"] is True
    finally:
        voice.clear_backend()
        restore_key()
    print("✓ Test 8 PASSED: wake word endpoints enforce key + bridge")


# 9
def test_wake_and_voice_off_device_report_android_only():
    voice.clear_backend()
    with client() as c:
        assert c.get("/api/voice/status").json()["android"] is False
        assert c.post("/api/wake/start", json={}).status_code == 409
        assert c.post("/api/wake/stop").status_code == 409
        r = c.post("/api/voice/transcribe", json={})
        assert r.status_code == 409 and "Android app" in r.json()["error"]
        st = c.get("/api/wake/status").json()
        assert st["supported"] is False and st["key_set"] is False
    print("✓ Test 9 PASSED: off-device voice features point to the Android app")


# 10
def test_android_bridge_sources_and_ui_ship():
    root = Path("mobile/android/app/src/main/java/ai/jarvis/assistant")
    voice_java = (root / "voice" / "VoiceBridge.java").read_text(encoding="utf-8")
    wake_java = (root / "voice" / "WakeBridge.java").read_text(encoding="utf-8")
    activity = (root / "MainActivity.java").read_text(encoding="utf-8")

    for marker in (
        "public static String speak(",
        "public static String stopSpeak()",
        "public static String voices(",
        "public static String status()",
        "public static String recognize(",
        "public static String record(",
        "SpeechRecognizer",
        "AudioRecord",
        "RIFF",
    ):
        assert marker in voice_java, marker

    for marker in (
        "public static String start(",
        "public static String stop()",
        "public static String status()",
        "PorcupineManager",
        "MainActivity.notifyWake",
    ):
        assert marker in wake_java, marker

    for marker in (
        "JarvisAndroid",
        "requestMicPermission",
        "public static void notifyWake(",
        "VoiceBridge.attach",
        "WakeBridge.attach",
    ):
        assert marker in activity, marker

    gradle = Path("mobile/android/app/build.gradle").read_text(encoding="utf-8")
    assert "ai.picovoice:porcupine-android" in gradle

    manifest = Path("mobile/android/app/src/main/AndroidManifest.xml").read_text(
        encoding="utf-8"
    )
    assert "android.permission.RECORD_AUDIO" in manifest

    html = Path("web/index.html").read_text(encoding="utf-8")
    for marker in ("chat-mic", "chat-speak", "voice-info", "wake-start", "wake-stop"):
        assert marker in html, marker

    js = Path("web/app.js").read_text(encoding="utf-8")
    for marker in (
        "/api/voice/status",
        "/api/voice/speak",
        "/api/voice/transcribe",
        "/api/wake/",
        "wakeAction",
        "onJarvisWake",
        "micTranscribe",
        "speakLast",
        "ensureMicPermission",
    ):
        assert marker in js, marker

    css = Path("web/style.css").read_text(encoding="utf-8")
    assert ".msg.system" in css and "button.rec" in css
    print("✓ Test 10 PASSED: Android bridges + web UI ship the voice features")


# 11
def test_voice_tools_stay_permission_gated_and_work():
    fake = FakeVoiceBridge()
    voice.set_backend(voice=fake)
    try:
        tools = {t.name: t for t in voice.get_voice_tools()}
        assert set(tools) == {
            "voice.status",
            "voice.speak",
            "voice.listen",
            "voice.transcribe",
            "voice.voices",
        }
        assert "voice.speak" in tools["voice.speak"].permissions
        assert tools["voice.listen"].permissions == ["voice.listen"]

        res = tools["voice.speak"].run(text="salam")
        assert res.success and res.result["provider"] == "android_tts"
        res = tools["voice.speak"].run(text="   ")
        assert not res.success

        res = tools["voice.listen"].run()
        assert res.success and res.result["transcript"] == "hello from speech"

        res = tools["voice.status"].run()
        assert res.success and res.result["tts"]["provider"] == "android_tts"

        res = tools["voice.transcribe"].run(audio_path="/etc/passwd")
        assert not res.success
    finally:
        voice.clear_backend()
    print("✓ Test 11 PASSED: Phase 11 voice tools are Android-aware and gated")
