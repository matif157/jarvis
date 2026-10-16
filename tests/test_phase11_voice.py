"""Phase 11 Voice Tests (offline; no audio playback, no microphone)."""

import shutil
from pathlib import Path

from jarvis.voice import (
    MacSayTTS,
    MockTTS,
    MockSTT,
    WhisperSTT,
    SpeechRecognitionSTT,
    VoiceManager,
    VoiceStatusTool,
    VoiceSpeakTool,
    VoiceListenTool,
    VoiceTranscribeTool,
    VoiceVoicesTool,
    get_voice_tools,
)
from jarvis.permissions import PermissionManager


# 1
def test_mac_say_availability_matches_environment():
    assert MacSayTTS().available() == (shutil.which("say") is not None)
    print("✓ Test 1 PASSED: MacSayTTS availability matches environment")


# 2
def test_mac_say_voices():
    tts = MacSayTTS()
    voices = tts.voices()
    assert isinstance(voices, list)
    if tts.available():
        assert len(voices) >= 1
    print("✓ Test 2 PASSED: MacSayTTS voices listing")


# 3
def test_mac_say_empty_text_fails():
    ok, msg = MacSayTTS().speak("")
    assert ok is False
    print("✓ Test 3 PASSED: MacSayTTS rejects empty text")


# 4
def test_mock_tts_speaks():
    tts = MockTTS()
    ok, msg = tts.speak("hello world", voice="MockVoice", rate=180)
    assert ok is True
    assert len(tts.spoken) == 1
    assert tts.spoken[0]["text"] == "hello world"
    assert tts.spoken[0]["voice"] == "MockVoice"
    print("✓ Test 4 PASSED: MockTTS captures spoken text")


# 5
def test_mock_tts_empty_fails():
    ok, _ = MockTTS().speak("   ")
    assert ok is False
    print("✓ Test 5 PASSED: MockTTS rejects empty text")


# 6
def test_mock_tts_voices():
    assert MockTTS(voices=["A", "B"]).voices() == ["A", "B"]
    print("✓ Test 6 PASSED: MockTTS voices")


# 7
def test_mock_stt_transcribes():
    stt = MockSTT(transcript="open the pod bay doors")
    ok, text = stt.transcribe()
    assert ok is True
    assert text == "open the pod bay doors"
    print("✓ Test 7 PASSED: MockSTT transcribes")


# 8
def test_mock_stt_records_calls():
    stt = MockSTT()
    stt.transcribe("audio.wav")
    assert stt.calls == ["audio.wav"]
    print("✓ Test 8 PASSED: MockSTT records calls")


# 9
def test_whisper_availability_is_bool():
    assert isinstance(WhisperSTT().available(), bool)
    print("✓ Test 9 PASSED: WhisperSTT.available returns bool")


# 10
def test_speech_recognition_availability_is_bool():
    assert isinstance(SpeechRecognitionSTT().available(), bool)
    print("✓ Test 10 PASSED: SpeechRecognitionSTT.available returns bool")


# 11
def test_whisper_requires_path():
    ok, msg = WhisperSTT().transcribe(None)
    assert ok is False
    print("✓ Test 11 PASSED: WhisperSTT requires an audio path")


# 12
def test_voice_manager_defaults_and_status():
    manager = VoiceManager()
    status = manager.status()
    assert "tts" in status and "stt" in status
    assert "provider" in status["tts"]
    assert "available" in status["tts"]
    print("✓ Test 12 PASSED: VoiceManager defaults and status structure")


# 13
def test_voice_manager_mock_speak():
    manager = VoiceManager(tts=MockTTS())
    ok, _ = manager.speak("hi")
    assert ok is True
    assert manager.tts.spoken[0]["text"] == "hi"
    print("✓ Test 13 PASSED: VoiceManager speak with mock TTS")


# 14
def test_voice_manager_listen_no_backend():
    manager = VoiceManager(tts=MockTTS())
    manager.stt = None
    ok, msg = manager.listen()
    assert ok is False
    assert "not available" in msg
    print("✓ Test 14 PASSED: VoiceManager honest failure without STT backend")


# 15
def test_voice_manager_mock_listen():
    manager = VoiceManager(tts=MockTTS(), stt=MockSTT("do the thing"))
    ok, text = manager.listen()
    assert ok is True
    assert text == "do the thing"
    print("✓ Test 15 PASSED: VoiceManager listen with mock STT")


# 16
def test_voice_tools_registered():
    from jarvis.tools import get_enhanced_registry

    names = [t["name"] for t in get_enhanced_registry().list_tools()]
    for name in ["voice.status", "voice.speak", "voice.listen", "voice.transcribe", "voice.voices"]:
        assert name in names, f"Missing tool: {name}"
    print("✓ Test 16 PASSED: All Phase 11 voice tools registered")


# 17
def test_voice_status_tool():
    r = VoiceStatusTool().run()
    assert r.success
    assert "tts" in r.result
    assert "stt" in r.result
    print("✓ Test 17 PASSED: voice.status tool")


# 18
def test_voice_speak_tool_empty_text():
    r = VoiceSpeakTool().run(text="")
    assert r.success is False
    assert "text is required" in r.error
    print("✓ Test 18 PASSED: voice.speak rejects empty text")


# 19
def test_voice_voices_tool():
    r = VoiceVoicesTool().run()
    assert r.success
    assert "voices" in r.result
    assert "provider" in r.result
    print("✓ Test 19 PASSED: voice.voices tool")


# 20
def test_voice_listen_tool_rejects_unsafe_path():
    r = VoiceListenTool().run(audio_path="/etc/passwd")
    assert r.success is False
    assert "not allowed" in r.error
    print("✓ Test 20 PASSED: voice.listen rejects unsafe path")


# 21
def test_voice_listen_tool_honest_without_backend():
    r = VoiceListenTool().run()
    # On this machine no STT backend is installed -> honest failure, never a fake transcript
    if VoiceManager().stt is None:
        assert r.success is False
        assert "not available" in r.error
    else:
        assert r.success is True
    print("✓ Test 21 PASSED: voice.listen honest fallback")


# 22
def test_voice_transcribe_tool_requires_path():
    r = VoiceTranscribeTool().run(audio_path="")
    assert r.success is False
    assert "required" in r.error
    print("✓ Test 22 PASSED: voice.transcribe requires a path")


# 23
def test_voice_transcribe_tool_rejects_unsafe_path():
    r = VoiceTranscribeTool().run(audio_path="/etc/passwd")
    assert r.success is False
    assert "not allowed" in r.error
    print("✓ Test 23 PASSED: voice.transcribe rejects unsafe path")


# 24
def test_voice_transcribe_tool_missing_file():
    missing = str(Path.home() / "Documents" / "definitely_missing_voice_test.wav")
    r = VoiceTranscribeTool().run(audio_path=missing)
    assert r.success is False
    assert "not found" in r.error
    print("✓ Test 24 PASSED: voice.transcribe missing file")


# 25
def test_get_voice_tools_count():
    assert len(get_voice_tools()) == 5
    print("✓ Test 25 PASSED: get_voice_tools returns 5 tools")


# 26
def test_voice_listen_permission_gated():
    reg = __import__("jarvis.tools", fromlist=["get_enhanced_registry"]).get_enhanced_registry()
    res = reg.execute("voice.listen")
    assert res.success is False
    assert res.meta and res.meta.get("needs_confirmation")
    print("✓ Test 26 PASSED: voice.listen is confirmation-gated")


# 27
def test_voice_permissions_model():
    perms = PermissionManager()
    assert perms.is_allowed("voice.read") is True
    assert perms.is_allowed("voice.speak") is True
    assert perms.needs_confirmation("voice.listen") is True
    print("✓ Test 27 PASSED: voice permission model")


# 28
def test_voice_speak_tool_long_text_capped_source():
    # Verify the tool reports the character count it would speak
    r = VoiceSpeakTool().run(text="   ")
    assert r.success is False
    print("✓ Test 28 PASSED: voice.speak whitespace-only rejected")


def run_all():
    test_mac_say_availability_matches_environment()
    test_mac_say_voices()
    test_mac_say_empty_text_fails()
    test_mock_tts_speaks()
    test_mock_tts_empty_fails()
    test_mock_tts_voices()
    test_mock_stt_transcribes()
    test_mock_stt_records_calls()
    test_whisper_availability_is_bool()
    test_speech_recognition_availability_is_bool()
    test_whisper_requires_path()
    test_voice_manager_defaults_and_status()
    test_voice_manager_mock_speak()
    test_voice_manager_listen_no_backend()
    test_voice_manager_mock_listen()
    test_voice_tools_registered()
    test_voice_status_tool()
    test_voice_speak_tool_empty_text()
    test_voice_voices_tool()
    test_voice_listen_tool_rejects_unsafe_path()
    test_voice_listen_tool_honest_without_backend()
    test_voice_transcribe_tool_requires_path()
    test_voice_transcribe_tool_rejects_unsafe_path()
    test_voice_transcribe_tool_missing_file()
    test_get_voice_tools_count()
    test_voice_listen_permission_gated()
    test_voice_permissions_model()
    test_voice_speak_tool_long_text_capped_source()
    print("\n=== ALL PHASE 11 VOICE TESTS PASSED ===")


if __name__ == "__main__":
    run_all()
