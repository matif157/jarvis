"""Voice I/O for Jarvis — text-to-speech and speech-to-text.

Local-first and honest about availability:
  - TTS uses the macOS ``say`` command (always available on macOS).
  - STT is pluggable; optional backends (``whisper`` / ``speech_recognition``)
    are used only when installed. When no backend is present, listening/
    transcription fails with a clear message rather than faking a transcript.

All providers are swappable so the rest of Jarvis (and the tests) can run
deterministically and offline via the mock providers.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .logging import get_logger
from .permissions import PermissionManager
from .security import is_path_safe
from .tools import Tool, ToolResult

logger = get_logger(__name__)

# Safety limits
MAX_SPEAK_CHARS = 2000
SPEAK_TIMEOUT_SECONDS = 60


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
        if not self.available():
            return False, "speech synthesis unavailable (no 'say' command)"
        if not text or not text.strip():
            return False, "nothing to speak"
        text = text[:MAX_SPEAK_CHARS]
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
        mac = MacSayTTS()
        return mac if mac.available() else MockTTS()

    @staticmethod
    def _default_stt() -> Optional[SpeechToTextProvider]:
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
            result={"spoken": True, "chars": len(text), "provider": manager.tts.name},
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
