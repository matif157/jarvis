"""Voice I/O for Jarvis — text-to-speech and speech-to-text.

Local-first and honest about availability:
  - TTS uses the macOS ``say`` command (always available on macOS) or the
    Android platform synthesiser through the in-app Java bridge.
  - STT is pluggable: optional backends (``whisper`` / ``speech_recognition``)
    run locally on the desktop, while the Android app records audio and
    recognises speech on-device (platform recognizer) or in the cloud (Groq
    Whisper, honouring ``engine.stt``).
  - The wake word ("Jarvis") is provided by Porcupine inside the Android app.

All providers are swappable so the rest of Jarvis (and the tests) can run
deterministically and offline via the mock providers.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .logging import get_logger
from .security import is_path_safe
from .service_keys import get_key as get_service_key
from .tools import Tool, ToolResult

logger = get_logger(__name__)

# Safety limits
MAX_SPEAK_CHARS = 2000
SPEAK_TIMEOUT_SECONDS = 60

# Cloud STT (used when engine.stt is "cloud"/"auto" fallback, and for files)
CLOUD_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
CLOUD_STT_MODEL = "whisper-large-v3-turbo"
CLOUD_STT_TIMEOUT = 60.0

# A ``voice`` argument that is really a language tag ("ur", "en-US")
LANGUAGE_TAG_RE = re.compile(r"^[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,8})?$")

# Urdu / cloud TTS (quality fix: stock voices read Urdu script with an
# English accent, so Urdu text falls back to Google Translate TTS.)
URDU_SCRIPT_RE = re.compile(r"[\u0600-\u06FF]")
TRANSLATE_TTS_URL = "https://translate.google.com/translate_tts"
TRANSLATE_TTS_TIMEOUT = 30.0
TTS_CHUNK_CHARS = 180  # the endpoint caps per-request length
TTS_USER_AGENT = "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36"


# ---------------------------------------------------------------------------
# Android bridges (Phase 20): platform TTS / speech recognition / wake word
# ---------------------------------------------------------------------------
class VoiceError(RuntimeError):
    """Raised when a voice feature cannot run in this environment."""


_voice_backend: Optional[Any] = None
_wake_backend: Optional[Any] = None
_voice_probed = False
_voice_cache: Any = None
_wake_probed = False
_wake_cache: Any = None


def set_backend(voice: Any = None, wake: Any = None) -> None:
    """Install bridge stand-ins (tests). Objects mirror the Java static APIs."""
    global _voice_backend, _wake_backend
    _voice_backend = voice
    _wake_backend = wake


def clear_backend() -> None:
    global _voice_backend, _wake_backend
    global _voice_cache, _voice_probed, _wake_cache, _wake_probed
    _voice_backend = None
    _wake_backend = None
    _voice_cache = None
    _voice_probed = False
    _wake_cache = None
    _wake_probed = False
    _urdu_voice_cache[0] = None


def _voice_bridge() -> Any:
    global _voice_cache, _voice_probed
    if _voice_backend is not None:
        return _voice_backend
    if not _voice_probed:
        _voice_probed = True
        try:
            from ai.jarvis.assistant.voice import VoiceBridge  # type: ignore

            _voice_cache = VoiceBridge
        except Exception:  # noqa: BLE001 - not running inside the Android app
            _voice_cache = None
    return _voice_cache


def _wake_bridge() -> Any:
    global _wake_cache, _wake_probed
    if _wake_backend is not None:
        return _wake_backend
    if not _wake_probed:
        _wake_probed = True
        try:
            from ai.jarvis.assistant.voice import WakeBridge  # type: ignore

            _wake_cache = WakeBridge
        except Exception:  # noqa: BLE001 - not running inside the Android app
            _wake_cache = None
    return _wake_cache


def is_android() -> bool:
    """True when running inside the Android app (Java bridges available)."""
    return _voice_bridge() is not None


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
    """Invoke a bridge method (JSON in / JSON out) and normalise failures."""
    fn = getattr(bridge, method)
    try:
        raw = fn(json.dumps(payload)) if payload is not None else fn()
    except Exception as exc:  # noqa: BLE001
        raise VoiceError(f"voice bridge failed: {exc}") from exc
    data = _as_dict(raw)
    if not data.get("ok"):
        raise VoiceError(str(data.get("error") or "voice bridge error"))
    return data


def android_status() -> Dict[str, Any]:
    """Platform TTS/microphone report from the Android bridge."""
    bridge = _voice_bridge()
    if bridge is None:
        return {"supported": False}
    try:
        data = _call(bridge, "status")
    except VoiceError as exc:
        return {"supported": True, "error": str(exc)}
    data["supported"] = True
    data.setdefault("platform", "android")
    return data


def detect_language(text: str) -> Optional[str]:
    """Best-effort language tag from the script of ``text``.

    Returns ``"ur-PK"`` when the text is predominantly Urdu (Arabic) script,
    otherwise None - callers keep their default (English) behaviour.
    """
    letters = [ch for ch in (text or "") if ch.isalpha()]
    if not letters:
        return None
    urdu = sum(1 for ch in letters if "\u0600" <= ch <= "\u06ff")
    if urdu / len(letters) > 0.3:
        return "ur-PK"
    return None


_urdu_voice_cache: Any = [None]  # None = unknown, True/False once probed


def _has_language_voice(language: str) -> bool:
    """Whether the local TTS engine reports voices for ``language`` (cached)."""
    tag = (language or "").split("-")[0].lower()
    if not tag:
        return False
    if tag == "ur" and _urdu_voice_cache[0] is not None:
        return bool(_urdu_voice_cache[0])
    voices = list_voices(tag) if is_android() else MacSayTTS().voices()
    has = any(
        tag in v.lower().replace("_", "-")
        or v.lower().startswith(tag)
        for v in voices
    )
    if tag == "ur":
        _urdu_voice_cache[0] = has
    return has


def _tts_chunks(text: str, limit: int = TTS_CHUNK_CHARS) -> List[str]:
    """Split ``text`` into TTS-sized pieces on whitespace."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return [text] if text else []
    chunks: List[str] = []
    current = ""
    for word in text.split(" "):
        if current and len(current) + 1 + len(word) > limit:
            chunks.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        chunks.append(current)
    return chunks


def _fetch_translate_tts(text: str, language: str) -> bytes:
    """Fetch one MP3 chunk from Google Translate TTS (no key required)."""
    import httpx

    lang = (language or "ur").split("-")[0]
    resp = httpx.get(
        TRANSLATE_TTS_URL,
        params={"ie": "UTF-8", "q": text[:TTS_CHUNK_CHARS], "tl": lang, "client": "tw-ob"},
        headers={"User-Agent": TTS_USER_AGENT},
        timeout=TRANSLATE_TTS_TIMEOUT,
    )
    if resp.status_code != 200 or not resp.content:
        raise VoiceError(f"cloud TTS failed (HTTP {resp.status_code})")
    head = resp.content[:3]
    if not (head == b"ID3" or (len(resp.content) > 1 and resp.content[0] == 0xFF)):
        raise VoiceError("cloud TTS returned non-audio data")
    return resp.content


def _play_audio_file(path: str) -> None:
    """Play an audio file: Android bridge on-device, ``afplay`` on macOS."""
    bridge = _voice_bridge()
    if bridge is not None:
        _call(bridge, "playAudio", {"path": path})
        return
    player = shutil.which("afplay")
    if not player:
        raise VoiceError("no audio player available on this system")
    try:
        subprocess.run([player, path], timeout=SPEAK_TIMEOUT_SECONDS, check=True)
    except subprocess.TimeoutExpired as exc:
        raise VoiceError("audio playback timed out") from exc
    except Exception as exc:  # noqa: BLE001
        raise VoiceError(f"audio playback failed: {exc}") from exc


def cloud_tts(text: str, language: str = "ur-PK") -> Dict[str, Any]:
    """Speak ``text`` via Google Translate TTS (chunked MP3, needs internet).

    Used when the platform synthesiser has no voice for the language - most
    stock Android/iOS/desktop engines read Urdu script with an English
    accent, which is exactly the complaint this fixes.
    """
    text = (text or "").strip()
    if not text:
        raise VoiceError("nothing to speak")
    chunks = _tts_chunks(text[:MAX_SPEAK_CHARS])
    if not chunks:
        raise VoiceError("nothing to speak")
    parts: List[bytes] = []
    try:
        for chunk in chunks:
            parts.append(_fetch_translate_tts(chunk, language))
    except VoiceError:
        raise
    except Exception as exc:  # noqa: BLE001 - network failures are user-facing
        raise VoiceError(f"cloud TTS failed: {exc}") from None
    fd, path = tempfile.mkstemp(prefix="jarvis-tts-", suffix=".mp3")
    try:
        with os.fdopen(fd, "wb") as fh:
            for part in parts:
                fh.write(part)
        _play_audio_file(path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    return {"ok": True, "provider": "cloud_tts", "language": language, "chars": len(text)}


def speak_text(
    text: str,
    language: Optional[str] = None,
    rate: Optional[float] = None,
) -> Dict[str, Any]:
    """Speak through the Android TTS engine (blocking until queued).

    When no language is given, Urdu (Arabic-script) text is auto-detected
    and spoken as ``ur-PK``; if the engine has no Urdu voice, a cloud TTS
    fallback speaks the text instead (the platform voice reading Urdu with
    an English accent is worse than a short network fetch).
    """
    text = (text or "").strip()
    if not text:
        raise VoiceError("nothing to speak")
    if not language:
        language = detect_language(text)
    if language and language.split("-")[0].lower() == "ur" and not _has_language_voice("ur"):
        try:
            return cloud_tts(text, language)
        except VoiceError as exc:
            logger.warning(f"cloud Urdu TTS unavailable ({exc}); using the platform voice")
    bridge = _voice_bridge()
    if bridge is None:
        raise VoiceError("android text-to-speech requires the Android app")
    payload: Dict[str, Any] = {"text": text[:MAX_SPEAK_CHARS]}
    if language:
        payload["language"] = language
    if rate:
        try:
            value = float(rate)
        except (TypeError, ValueError):
            value = 0.0
        if value > 4.0:  # words-per-minute style (macOS say) -> rate multiplier
            value = value / 175.0
        if 0.25 < value < 4.0:
            payload["rate"] = round(value, 2)
    return _call(bridge, "speak", payload)


def stop_speech() -> Dict[str, Any]:
    bridge = _voice_bridge()
    if bridge is None:
        raise VoiceError("android text-to-speech requires the Android app")
    return _call(bridge, "stopSpeak")


def list_voices(language: Optional[str] = None) -> List[str]:
    """Voice names reported by the Android TTS engine (empty on desktop)."""
    bridge = _voice_bridge()
    if bridge is None:
        return []
    payload: Dict[str, Any] = {"language": language} if language else {}
    try:
        data = _call(bridge, "voices", payload)
    except VoiceError as exc:  # pragma: no cover - OEM engine quirks
        logger.warning(f"Failed to list android voices: {exc}")
        return []
    return [str(v) for v in data.get("voices", [])]


def recognize_speech(language: Optional[str] = None, timeout_ms: Optional[int] = None) -> str:
    """Live microphone transcription via the platform recognizer (blocking)."""
    bridge = _voice_bridge()
    if bridge is None:
        raise VoiceError("live speech recognition requires the Android app")
    payload: Dict[str, Any] = {}
    if language:
        payload["language"] = language
    if timeout_ms:
        payload["timeout_ms"] = int(timeout_ms)
    data = _call(bridge, "recognize", payload)
    text = str(data.get("text") or "").strip()
    if not text:
        raise VoiceError("nothing recognized - try speaking again")
    return text


def record_wav(seconds: int = 8) -> str:
    """Record microphone audio to a WAV file (blocking); returns its path."""
    bridge = _voice_bridge()
    if bridge is None:
        raise VoiceError("audio recording requires the Android app")
    data = _call(bridge, "record", {"seconds": int(seconds)})
    path = str(data.get("path") or "")
    if not path:
        raise VoiceError("recording failed")
    return path


def cloud_transcribe(
    audio_path: str,
    language: Optional[str] = None,
    check_path: bool = True,
) -> Tuple[bool, str]:
    """Transcribe a file with Groq's Whisper. Needs a Groq API key.

    ``check_path=False`` is used only for recordings produced by our own
    bridge (their location is fixed by Java, outside the usual safe bases).
    """
    if check_path and (not is_path_safe(audio_path) or not Path(audio_path).exists()):
        return False, "audio file not found or not allowed"
    from . import llm  # local import: llm must not load for every voice call

    key = llm.provider_key("groq")
    if not key:
        return False, "cloud transcription needs a Groq API key (Settings > Service API keys)"
    try:
        import httpx

        form: Dict[str, Any] = {"model": CLOUD_STT_MODEL}
        if language:
            form["language"] = language.split("-")[0]
        with open(audio_path, "rb") as fh:
            resp = httpx.post(
                CLOUD_STT_URL,
                headers={"Authorization": f"Bearer {key}"},
                files={"file": (Path(audio_path).name, fh, "audio/wav")},
                data=form,
                timeout=CLOUD_STT_TIMEOUT,
            )
        if resp.status_code != 200:
            detail = ""
            try:
                detail = str(resp.json().get("error", {}).get("message", ""))
            except Exception:  # noqa: BLE001
                pass
            logger.warning(f"Groq transcription failed: HTTP {resp.status_code} {detail[:120]}")
            return False, f"cloud transcription failed (HTTP {resp.status_code})"
        text = str(resp.json().get("text", "")).strip()
        if not text:
            return False, "nothing recognized in the recording"
        return True, text
    except Exception as exc:  # noqa: BLE001 - network/provider failures
        return False, f"cloud transcription failed: {exc}"


def wake_start(access_key: str, keyword: str = "jarvis") -> Dict[str, Any]:
    """Start Porcupine wake-word listening inside the Android app."""
    bridge = _wake_bridge()
    if bridge is None:
        raise VoiceError("wake word requires the Android app")
    if not access_key:
        raise VoiceError(
            "a Picovoice access key is required (Settings > Service API keys)"
        )
    return _call(
        bridge,
        "start",
        {"access_key": access_key, "keyword": (keyword or "jarvis").strip().lower()},
    )


def wake_stop() -> Dict[str, Any]:
    bridge = _wake_bridge()
    if bridge is None:
        raise VoiceError("wake word requires the Android app")
    return _call(bridge, "stop")


def wake_status() -> Dict[str, Any]:
    """Wake-word state; ``supported`` is false off-device."""
    bridge = _wake_bridge()
    if bridge is None:
        return {"supported": False}
    try:
        data = _call(bridge, "status")
    except VoiceError as exc:
        return {"supported": True, "error": str(exc)}
    data["supported"] = True
    return data


def wake_keywords() -> List[str]:
    """Built-in wake words offered by the Porcupine Android SDK."""
    bridge = _wake_bridge()
    if bridge is None:
        return []
    try:
        data = _call(bridge, "keywords")
    except VoiceError:  # pragma: no cover - bridge quirk
        return []
    return [str(k) for k in data.get("keywords", [])]


# ---------------------------------------------------------------------------
# Text-to-speech
# ---------------------------------------------------------------------------
class TextToSpeechProvider(ABC):
    """Abstract base class for text-to-speech providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier."""

    @abstractmethod
    def available(self) -> bool:
        """Whether this provider can be used on this machine."""

    def voices(self) -> List[str]:
        """Return available voice names (may be empty)."""
        return []

    @abstractmethod
    def speak(self, text: str, voice: Optional[str] = None, rate: Optional[int] = None) -> Tuple[bool, str]:
        """Speak ``text``. Return (success, message)."""


class MacSayTTS(TextToSpeechProvider):
    """macOS ``say`` command text-to-speech."""

    last_provider = None  # actual backend used by the latest speak() call

    @property
    def name(self) -> str:
        return "macos_say"

    def available(self) -> bool:
        return shutil.which("say") is not None

    def voices(self) -> List[str]:
        if not self.available():
            return []
        try:
            out = subprocess.run(
                ["say", "-v", "?"],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout
            voices = []
            for line in out.splitlines():
                line = line.strip()
                if line:
                    # Format: "Samantha            en_US    # comment"
                    voices.append(line.split()[0])
            return voices
        except Exception as exc:  # pragma: no cover - environment dependent
            logger.warning(f"Failed to list voices: {exc}")
            return []

    def speak(self, text: str, voice: Optional[str] = None, rate: Optional[int] = None) -> Tuple[bool, str]:
        if not text or not text.strip():
            return False, "nothing to speak"
        text = text[:MAX_SPEAK_CHARS]
        # ``say`` ships no Urdu voice: Urdu script goes to the cloud TTS.
        if not voice and detect_language(text):
            try:
                cloud_tts(text, "ur-PK")
                self.last_provider = "cloud_tts"
                return True, "spoken"
            except VoiceError as exc:
                logger.warning(f"cloud Urdu TTS unavailable ({exc}); using 'say'")
        if not self.available():
            return False, "speech synthesis unavailable (no 'say' command)"
        self.last_provider = "macos_say"
        cmd = ["say"]
        if voice:
            cmd.extend(["-v", voice])
        if rate:
            cmd.extend(["-r", str(int(rate))])
        cmd.append(text)
        try:
            subprocess.run(cmd, timeout=SPEAK_TIMEOUT_SECONDS, check=True)
            return True, "spoken"
        except subprocess.TimeoutExpired:
            return False, "speech timed out"
        except Exception as exc:
            return False, f"speech failed: {exc}"


class MockTTS(TextToSpeechProvider):
    """Deterministic TTS provider for tests (records spoken text)."""

    def __init__(self, voices: Optional[List[str]] = None):
        self.spoken: List[Dict[str, Any]] = []
        self._voices = voices if voices is not None else ["MockVoice"]

    @property
    def name(self) -> str:
        return "mock"

    def available(self) -> bool:
        return True

    def voices(self) -> List[str]:
        return list(self._voices)

    def speak(self, text: str, voice: Optional[str] = None, rate: Optional[int] = None) -> Tuple[bool, str]:
        if not text or not text.strip():
            return False, "nothing to speak"
        self.spoken.append({"text": text, "voice": voice, "rate": rate})
        return True, "spoken"


class AndroidTTS(TextToSpeechProvider):
    """Android platform synthesiser through the in-app Java bridge."""

    last_provider = None  # actual backend used by the latest speak() call

    @property
    def name(self) -> str:
        return "android_tts"

    def available(self) -> bool:
        return is_android()

    def voices(self) -> List[str]:
        if not self.available():
            return []
        return list_voices()

    def speak(self, text: str, voice: Optional[str] = None, rate: Optional[int] = None) -> Tuple[bool, str]:
        if not self.available():
            return False, "android text-to-speech is not available here"
        if not text or not text.strip():
            return False, "nothing to speak"
        # ``voice`` may be a language tag ("ur", "en-US"); anything else is
        # ignored because the platform engine selects voices itself. With no
        # explicit voice, Urdu script is auto-detected inside speak_text.
        language = voice if voice and LANGUAGE_TAG_RE.match(voice) else None
        try:
            data = speak_text(text, language=language, rate=rate)
            self.last_provider = data.get("provider", "android_tts")
            return True, "spoken"
        except VoiceError as exc:
            return False, str(exc)


# ---------------------------------------------------------------------------
# Speech-to-text
# ---------------------------------------------------------------------------
class SpeechToTextProvider(ABC):
    """Abstract base class for speech-to-text providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier."""

    @abstractmethod
    def available(self) -> bool:
        """Whether this provider can be used on this machine."""

    @abstractmethod
    def transcribe(self, audio_path: Optional[str] = None) -> Tuple[bool, str]:
        """Transcribe audio to text. Return (success, text_or_error)."""


class WhisperSTT(SpeechToTextProvider):
    """OpenAI Whisper backend (only if the ``whisper`` package is installed)."""

    @property
    def name(self) -> str:
        return "whisper"

    def available(self) -> bool:
        try:
            import whisper  # noqa: F401
        except Exception:
            return False
        return True

    def transcribe(self, audio_path: Optional[str] = None) -> Tuple[bool, str]:
        if not self.available():
            return False, "whisper not installed"
        if not audio_path:
            return False, "an audio file is required for whisper transcription"
        if not is_path_safe(audio_path) or not Path(audio_path).exists():
            return False, "audio file not found or not allowed"
        try:
            import whisper

            model = whisper.load_model("base")
            result = model.transcribe(audio_path)
            return True, result.get("text", "").strip()
        except Exception as exc:  # pragma: no cover - heavy/optional
            return False, f"transcription failed: {exc}"


class SpeechRecognitionSTT(SpeechToTextProvider):
    """``speech_recognition`` backend (only if installed)."""

    @property
    def name(self) -> str:
        return "speech_recognition"

    def available(self) -> bool:
        try:
            import speech_recognition  # noqa: F401
        except Exception:
            return False
        return True

    def transcribe(self, audio_path: Optional[str] = None) -> Tuple[bool, str]:
        if not self.available():
            return False, "speech_recognition not installed"
        if not audio_path:
            return False, "an audio file is required for speech_recognition transcription"
        if not is_path_safe(audio_path) or not Path(audio_path).exists():
            return False, "audio file not found or not allowed"
        try:
            import speech_recognition as sr

            recognizer = sr.Recognizer()
            with sr.AudioFile(audio_path) as source:
                audio = recognizer.record(source)
            return True, recognizer.recognize_google(audio)
        except Exception as exc:  # pragma: no cover - optional
            return False, f"transcription failed: {exc}"


class MockSTT(SpeechToTextProvider):
    """Deterministic STT provider for tests."""

    def __init__(self, transcript: str = "hello jarvis"):
        self.transcript = transcript
        self.calls: List[Optional[str]] = []

    @property
    def name(self) -> str:
        return "mock"

    def available(self) -> bool:
        return True

    def transcribe(self, audio_path: Optional[str] = None) -> Tuple[bool, str]:
        self.calls.append(audio_path)
        return True, self.transcript


class AndroidSTT(SpeechToTextProvider):
    """Android platform speech recognizer (live microphone, on-device)."""

    @property
    def name(self) -> str:
        return "android_speech"

    def available(self) -> bool:
        return is_android()

    def transcribe(self, audio_path: Optional[str] = None) -> Tuple[bool, str]:
        if not self.available():
            return False, "android speech recognition is not available here"
        if audio_path:
            return False, (
                "on-device recognition needs live audio; "
                "transcribe files with a cloud STT key"
            )
        try:
            return True, recognize_speech()
        except VoiceError as exc:
            return False, str(exc)


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------
class VoiceManager:
    """Coordinate a TTS provider and an STT provider with fallback."""

    def __init__(
        self,
        tts: Optional[TextToSpeechProvider] = None,
        stt: Optional[SpeechToTextProvider] = None,
    ):
        self.tts = tts or self._default_tts()
        self.stt = stt if stt is not None else self._default_stt()

    @staticmethod
    def _default_tts() -> TextToSpeechProvider:
        android = AndroidTTS()
        if android.available():
            return android
        mac = MacSayTTS()
        return mac if mac.available() else MockTTS()

    @staticmethod
    def _default_stt() -> Optional[SpeechToTextProvider]:
        android = AndroidSTT()
        if android.available():
            return android
        for provider in (WhisperSTT(), SpeechRecognitionSTT()):
            if provider.available():
                return provider
        return None

    def speak(self, text: str, voice: Optional[str] = None, rate: Optional[int] = None) -> Tuple[bool, str]:
        return self.tts.speak(text, voice=voice, rate=rate)

    def listen(self, audio_path: Optional[str] = None) -> Tuple[bool, str]:
        if self.stt is None:
            return False, "speech-to-text backend not available (install whisper or speech_recognition)"
        return self.stt.transcribe(audio_path)

    def status(self) -> Dict[str, Any]:
        return {
            "tts": {
                "provider": self.tts.name,
                "available": self.tts.available(),
                "voice_count": len(self.tts.voices()),
            },
            "stt": {
                "provider": self.stt.name if self.stt else None,
                "available": self.stt is not None and self.stt.available(),
            },
        }


# ---------------------------------------------------------------------------
# Orchestrators (Phase 20): engine routing + combined status
# ---------------------------------------------------------------------------
def status_payload() -> Dict[str, Any]:
    """Combined voice report for ``GET /api/voice/status``."""
    from . import engines

    try:
        base = VoiceManager().status()
    except Exception:  # noqa: BLE001 - a broken provider must not 500 the UI
        base = {"tts": {"available": False}, "stt": {"available": False}}
    out: Dict[str, Any] = {
        "ok": True,
        "android": is_android(),
        "tts": base.get("tts", {}),
        "stt": base.get("stt", {}),
        "stt_engine": engines.get("stt") or "auto",
        "wake": wake_status(),
        "wake_key_set": bool(get_service_key("picovoice")),
        "wake_keywords": wake_keywords(),
    }
    if out["android"]:
        out["device"] = android_status()
    return out


def transcribe_live(
    language: Optional[str] = None,
    seconds: int = 8,
    mode: Optional[str] = None,
) -> Tuple[bool, str, str]:
    """Live transcription honouring ``engine.stt``.

    Returns ``(ok, transcript_or_error, provider)``.
    """
    from . import engines

    if mode is None:
        mode = engines.get("stt") or "auto"

    if mode == "cloud":
        if not is_android():
            return False, "live capture requires the Android app", "cloud"
        try:
            path = record_wav(seconds)
        except VoiceError as exc:
            return False, str(exc), "cloud"
        ok, text = cloud_transcribe(path, language, check_path=False)
        return ok, text, "groq_whisper"

    # on_device / auto: prefer the platform recognizer, then fall back.
    if is_android():
        try:
            return True, recognize_speech(language=language), "android_speech"
        except VoiceError as exc:
            if mode == "on_device":
                return False, str(exc), "android_speech"
            try:
                path = record_wav(seconds)
            except VoiceError as rec_exc:
                return False, f"{exc}; fallback recording failed: {rec_exc}", "cloud"
            ok, text = cloud_transcribe(path, language, check_path=False)
            if ok:
                return True, text, "groq_whisper"
            return False, f"{exc}; cloud fallback failed: {text}", "cloud"

    reason = (
        "on-device speech recognition requires the Android app"
        if mode == "on_device"
        else "live capture requires the Android app"
    )
    return False, reason, mode


def transcribe_file(
    audio_path: str,
    language: Optional[str] = None,
) -> Tuple[bool, str, str]:
    """File transcription: installed desktop STT when present, else cloud.

    Returns ``(ok, transcript_or_error, provider)``.
    """
    if not is_path_safe(audio_path) or not Path(audio_path).exists():
        return False, "audio file not found or not allowed", "local"
    manager = VoiceManager()
    stt = manager.stt
    if stt is not None and stt.name in {"whisper", "speech_recognition"} and stt.available():
        ok, text = stt.transcribe(audio_path)
        if ok or "not installed" not in text:
            return ok, text, stt.name
    ok, text = cloud_transcribe(audio_path, language)
    return ok, text, "groq_whisper"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
class VoiceStatusTool(Tool):
    name = "voice.status"
    description = "Report text-to-speech and speech-to-text availability"
    permissions = ["voice.read"]

    def run(self) -> ToolResult:
        return ToolResult(success=True, result=VoiceManager().status(), tool=self.name)


class VoiceSpeakTool(Tool):
    name = "voice.speak"
    description = "Speak text aloud using the system voice"
    permissions = ["voice.speak"]

    def run(self, text: str, voice: str = "", rate: int = 0) -> ToolResult:
        if not text or not text.strip():
            return ToolResult(success=False, error="text is required", tool=self.name)
        manager = VoiceManager()
        success, message = manager.speak(text, voice=voice or None, rate=rate or None)
        if not success:
            return ToolResult(success=False, error=message, tool=self.name)
        return ToolResult(
            success=True,
            result={
                "spoken": True,
                "chars": len(text),
                "provider": getattr(manager.tts, "last_provider", None) or manager.tts.name,
            },
            tool=self.name,
        )


class VoiceListenTool(Tool):
    name = "voice.listen"
    description = "Transcribe speech to text (requires a configured STT backend)"
    permissions = ["voice.listen"]

    def run(self, audio_path: str = "") -> ToolResult:
        manager = VoiceManager()
        if audio_path and not is_path_safe(audio_path):
            return ToolResult(success=False, error="audio path not allowed", tool=self.name)
        success, result = manager.listen(audio_path or None)
        if not success:
            return ToolResult(success=False, error=result, tool=self.name)
        return ToolResult(
            success=True,
            result={"transcript": result, "provider": manager.stt.name if manager.stt else None},
            tool=self.name,
        )


class VoiceTranscribeTool(Tool):
    name = "voice.transcribe"
    description = "Transcribe a local audio file to text"
    permissions = ["voice.listen"]

    def run(self, audio_path: str) -> ToolResult:
        if not audio_path:
            return ToolResult(success=False, error="audio_path is required", tool=self.name)
        if not is_path_safe(audio_path):
            return ToolResult(success=False, error="audio path not allowed", tool=self.name)
        if not Path(audio_path).exists():
            return ToolResult(success=False, error="audio file not found", tool=self.name)
        manager = VoiceManager()
        success, result = manager.listen(audio_path)
        if not success:
            return ToolResult(success=False, error=result, tool=self.name)
        return ToolResult(
            success=True,
            result={"transcript": result, "path": audio_path},
            tool=self.name,
        )


class VoiceVoicesTool(Tool):
    name = "voice.voices"
    description = "List available text-to-speech voices"
    permissions = ["voice.read"]

    def run(self) -> ToolResult:
        manager = VoiceManager()
        voices = manager.tts.voices()
        return ToolResult(
            success=True,
            result={"provider": manager.tts.name, "count": len(voices), "voices": voices},
            tool=self.name,
        )


def get_voice_tools() -> List[Tool]:
    """Return all Phase 11 voice tools."""
    return [
        VoiceStatusTool(),
        VoiceSpeakTool(),
        VoiceListenTool(),
        VoiceTranscribeTool(),
        VoiceVoicesTool(),
    ]


def get_voice_tools_for_registry() -> List[Tool]:
    return get_voice_tools()
