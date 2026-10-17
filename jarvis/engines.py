"""Engine selection: where Jarvis runs each model (cloud vs on-device).

Choices are persisted in the ``settings`` table under ``engine.<component>``
so they survive restarts. Three components:

* ``llm``   — chat / reasoning
* ``stt``   — speech-to-text
* ``image`` — image generation

The storage and validation layer lands now so the Settings UI, the API and the
future consumers all share one source of truth; each component takes effect as
its feature is implemented (on-device LLM, mobile voice, local image service).
Values are validated against ``ENGINES`` before they are stored, so bad values
never reach the database.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from . import db

ENGINES: Dict[str, Dict[str, object]] = {
    "llm": {
        "label": "Chat (LLM)",
        "description": "Where answers are generated.",
        "default": "auto",
        "options": [
            {"value": "auto", "label": "Auto - cloud when a key is set, on-device otherwise"},
            {"value": "cloud", "label": "Cloud only (Groq / OpenRouter / Gemini)"},
            {"value": "on_device", "label": "On-device only (offline, private)"},
        ],
    },
    "stt": {
        "label": "Speech-to-text",
        "description": "How your voice is transcribed.",
        "default": "on_device",
        "options": [
            {"value": "on_device", "label": "On-device (offline, private)"},
            {"value": "cloud", "label": "Cloud (faster, needs a key + network)"},
            {"value": "auto", "label": "Auto - on-device when offline"},
        ],
    },
    "image": {
        "label": "Image generation",
        "description": "Where images are created.",
        "default": "local",
        "options": [
            {"value": "local", "label": "Local service (your own machine, free)"},
            {"value": "cloud", "label": "Cloud (needs a provider key)"},
            {"value": "off", "label": "Off (no image generation)"},
        ],
    },
}


def _values(name: str) -> List[str]:
    return [str(o["value"]) for o in ENGINES[name]["options"]]


def known(name: str) -> bool:
    return name in ENGINES


def valid(name: str, value: str) -> bool:
    return name in ENGINES and value in _values(name)


def get(name: str, default: Optional[str] = None) -> Optional[str]:
    """Current choice for a component; falls back to its default."""
    spec = ENGINES.get(name)
    if spec is None:
        return default
    stored = db.get_setting(f"engine.{name}")
    if stored and stored in _values(name):
        return stored
    return str(spec["default"])


def set(name: str, value: str) -> bool:
    """Persist a choice; rejects unknown components and invalid values."""
    if not valid(name, value):
        return False
    db.set_setting(f"engine.{name}", value)
    return True


def snapshot() -> Dict[str, Dict[str, object]]:
    """Full description of every component (value, default, options, labels)."""
    out: Dict[str, Dict[str, object]] = {}
    for name, spec in ENGINES.items():
        out[name] = {
            "label": spec["label"],
            "description": spec["description"],
            "value": get(name),
            "default": spec["default"],
            "options": spec["options"],
        }
    return out
