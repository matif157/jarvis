"""Phase 23 — Urdu TTS quality: script auto-detect + cloud fallback.

Stock Android/macOS voices read Urdu (Arabic) script with an English accent.
These checks cover the detection heuristic, chunked Google-Translate-TTS
fetching against a throwaway local server, the Android ``playAudio`` bridge
hand-off, endpoint reporting, and honest fallbacks - all offline.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fastapi.testclient import TestClient

from jarvis import voice
from jarvis.app import app

URDU_TEXT = "\u0633\u0644\u0627\u0645 \u0628\u062d\u0627\u0626\u06cc\u060c \u06a9\u064a\u0633\u0627\u0647\u0648\u061f"
ENGLISH_TEXT = "hello there, how are you today?"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeTtsBridge:
    """Android voice bridge without an Urdu voice (the quality-gap case)."""

    def __init__(self, voices_list=None):
        self.spoken = []
        self.played = []
        self.voices_list = voices_list if voices_list is not None else ["en-US-local"]

    def speak(self, request_json):
        self.spoken.append(json.loads(request_json))
        return {"ok": True, "provider": "android_tts"}

    def stopSpeak(self):
        return {"ok": True}

    def voices(self, request_json):
        return {"ok": True, "voices": list(self.voices_list)}

    def playAudio(self, request_json):
        request = json.loads(request_json)
        path = Path(request["path"])
        assert path.exists() and path.stat().st_size > 0, "temp mp3 missing"
        self.played.append(str(path))
        return {"ok": True, "duration_ms": 42}

    def status(self):
        return {
            "ok": True,
            "tts": {"ready": True, "initialised": True, "speaking": False},
            "mic": {"granted": True},
        }


class _TtsHandler(BaseHTTPRequestHandler):
    """Minimal Google-Translate-TTS lookalike."""

    def log_message(self, *args):
        pass

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        if "error" in self.path:
            payload, code = b"nope", 403
        elif "html" in self.path:
            payload, code = b"<html>blocked</html>", 200
        else:
            payload, code = b"ID3\x03\x00\x00\x00\x00\x00\x00fake-mp3-bytes", 200
        self.send_response(code)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def serve():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _TtsHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def fake_cloud(srv_port):
    """Point the TTS fetcher at the local server; returns a restore fn."""
    original = voice.TRANSLATE_TTS_URL
    voice.TRANSLATE_TTS_URL = f"http://127.0.0.1:{srv_port}/translate_tts"

    def restore():
        voice.TRANSLATE_TTS_URL = original

    return restore


# 1
def test_detect_language_script_heuristic():
    assert voice.detect_language(URDU_TEXT) == "ur-PK"
    assert voice.detect_language("\u0627\u064a\u06a9 \u062f\u0646\u064a\u0627 \u0647\u064a\u060c \u06a9\u064a\u0633\u0627 \u06c1\u0648\u061f") == "ur-PK"
    assert voice.detect_language(ENGLISH_TEXT) is None
    assert voice.detect_language("salam, kya haal hai?") is None  # roman Urdu = latin script
    assert voice.detect_language("  \n\t ") is None
    assert voice.detect_language("!!! ??? ...") is None
    # a mostly-English line with one Urdu word stays English
    assert voice.detect_language("thanks for the message, \u0633\u0644\u0627\u0645 is how we greet") is None
    print("✓ Test 1 PASSED: Urdu script detection is precise")


# 2
def test_tts_chunking_respects_the_endpoint_limit():
    assert voice._tts_chunks("") == []
    assert voice._tts_chunks("short line") == ["short line"]
    long_text = " ".join(["word"] * 120)  # 599 chars
    chunks = voice._tts_chunks(long_text)
    assert len(chunks) > 1
    assert all(len(c) <= voice.TTS_CHUNK_CHARS for c in chunks)
    assert " ".join(chunks) == long_text  # nothing lost
    print("✓ Test 2 PASSED: long text splits into TTS-sized chunks")


# 3
def test_cloud_tts_fetches_plays_and_cleans_up():
    srv, port = serve()
    restore_url = fake_cloud(port)
    fake = FakeTtsBridge()
    voice.set_backend(voice=fake)
    try:
        data = voice.cloud_tts(URDU_TEXT)
        assert data == {
            "ok": True,
            "provider": "cloud_tts",
            "language": "ur-PK",
            "chars": len(URDU_TEXT),
        }
        assert len(fake.played) == 1  # temp mp3 handed to playAudio then removed
        assert not Path(fake.played[0]).exists()

        try:
            voice.cloud_tts("   ")
            assert False
        except voice.VoiceError as exc:
            assert "nothing to speak" in str(exc)

        voice.TRANSLATE_TTS_URL = f"http://127.0.0.1:{port}/translate_tts&error=1"
        try:
            voice.cloud_tts(URDU_TEXT)
            assert False
        except voice.VoiceError as exc:
            assert "HTTP 403" in str(exc)

        voice.TRANSLATE_TTS_URL = f"http://127.0.0.1:{port}/translate_tts&html=1"
        try:
            voice.cloud_tts(URDU_TEXT)
            assert False
        except voice.VoiceError as exc:
            assert "non-audio" in str(exc)
    finally:
        restore_url()
        voice.clear_backend()
        srv.shutdown()
    print("✓ Test 3 PASSED: cloud TTS fetches, plays and cleans up")


# 4
def test_speak_text_auto_detects_and_routes_urdu():
    srv, port = serve()
    restore_url = fake_cloud(port)
    try:
        # no Urdu voice on the platform -> cloud path, platform untouched
        fake = FakeTtsBridge(voices_list=["en-US-local"])
        voice.set_backend(voice=fake)
        data = voice.speak_text(URDU_TEXT)
        assert data["provider"] == "cloud_tts" and data["language"] == "ur-PK"
        assert fake.spoken == [] and len(fake.played) == 1

        # English text still goes to the platform, no language forced
        voice.speak_text(ENGLISH_TEXT)
        assert fake.spoken[-1]["text"] == ENGLISH_TEXT
        assert "language" not in fake.spoken[-1]

        # explicit language wins over detection
        voice.speak_text(ENGLISH_TEXT, language="en-US")
        assert fake.spoken[-1]["language"] == "en-US"

        # a device WITH an Urdu voice uses it - no network
        voice.clear_backend()
        fake2 = FakeTtsBridge(voices_list=["ur-PK-local", "en-US-local"])
        voice.set_backend(voice=fake2)
        data = voice.speak_text(URDU_TEXT)
        assert data["provider"] == "android_tts"
        assert fake2.spoken[-1]["language"] == "ur-PK"
        assert fake2.played == []

        # cloud failure degrades to the platform voice (with the tag)
        voice.clear_backend()
        fake3 = FakeTtsBridge(voices_list=["en-US-local"])
        voice.set_backend(voice=fake3)
        voice.TRANSLATE_TTS_URL = f"http://127.0.0.1:{port}/translate_tts&error=1"
        data = voice.speak_text(URDU_TEXT)
        assert data["provider"] == "android_tts"
        assert fake3.spoken[-1]["language"] == "ur-PK"
    finally:
        restore_url()
        voice.clear_backend()
        srv.shutdown()
    print("✓ Test 4 PASSED: speak_text routes Urdu by device capability")


# 5
def test_macsay_uses_cloud_for_urdu():
    srv, port = serve()
    restore_url = fake_cloud(port)
    fake = FakeTtsBridge()
    voice.set_backend(voice=fake)  # cloud playAudio goes through the bridge
    spoken_say = []
    original_run = voice.subprocess.run

    def fake_run(cmd, **kwargs):
        spoken_say.append(cmd)
        return type("R", (), {"returncode": 0})()

    voice.subprocess.run = fake_run
    try:
        mac = voice.MacSayTTS()
        mac.available = lambda: True  # deterministic on CI (Linux has no `say`)
        ok, message = mac.speak(URDU_TEXT)
        assert ok and message == "spoken"
        assert spoken_say == []  # never reached `say`
        assert len(fake.played) == 1

        ok, message = mac.speak(ENGLISH_TEXT)
        assert ok and spoken_say and spoken_say[0][0] == "say"
        assert ENGLISH_TEXT in spoken_say[0]

        # an explicit voice disables the cloud shortcut
        spoken_say.clear()
        ok, message = mac.speak(URDU_TEXT, voice="Samantha")
        assert ok and spoken_say and "-v" in spoken_say[0]
    finally:
        voice.subprocess.run = original_run
        restore_url()
        voice.clear_backend()
        srv.shutdown()
    print("✓ Test 5 PASSED: macOS say falls back to cloud TTS for Urdu")


# 6
def test_endpoint_reports_the_real_provider_and_java_ships_playaudio():
    srv, port = serve()
    restore_url = fake_cloud(port)
    fake = FakeTtsBridge(voices_list=["en-US-local"])
    voice.set_backend(voice=fake)
    try:
        with TestClient(app) as c:
            r = c.post("/api/voice/speak", json={"text": URDU_TEXT})
            assert r.status_code == 200, r.json()
            body = r.json()
            assert body["ok"] is True
            assert body["provider"] == "cloud_tts"
            assert body["language"] == "ur-PK"
            assert fake.spoken == []

            r = c.post("/api/voice/speak", json={"text": ENGLISH_TEXT})
            assert r.json()["provider"] == "android_tts"
            assert "language" not in r.json()
    finally:
        restore_url()
        voice.clear_backend()
        srv.shutdown()

    java = Path(
        "mobile/android/app/src/main/java/ai/jarvis/assistant/voice/VoiceBridge.java"
    ).read_text(encoding="utf-8")
    for marker in (
        "public static String playAudio(",
        "MediaPlayer",
        "setDataSource",
        "CountDownLatch",
    ):
        assert marker in java, marker
    print("✓ Test 6 PASSED: endpoint reports cloud_tts and Java ships playAudio")


# 7
def test_voice_manager_and_tool_stay_compatible():
    srv, port = serve()
    restore_url = fake_cloud(port)
    fake = FakeTtsBridge(voices_list=["en-US-local"])
    voice.set_backend(voice=fake)
    try:
        manager = voice.VoiceManager()
        assert manager.tts.name == "android_tts"
        ok, message = manager.speak(URDU_TEXT)
        assert ok and message == "spoken"
        assert len(fake.played) == 1

        tools = {t.name: t for t in voice.get_voice_tools()}
        res = tools["voice.speak"].run(text=URDU_TEXT)
        assert res.success and res.result["provider"] == "cloud_tts"
        res = tools["voice.speak"].run(text="   ")
        assert not res.success
    finally:
        restore_url()
        voice.clear_backend()
        srv.shutdown()
    print("✓ Test 7 PASSED: manager + tools stay compatible with the fix")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name} PASSED")
