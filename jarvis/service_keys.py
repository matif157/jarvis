"""Third-party service API keys (non-LLM), stored locally and masked.

These are distinct from the LLM provider keys managed in ``jarvis/llm.py``:
service tokens authenticate auxiliary services (e.g. Hugging Face for image
generation / model downloads, Picovoice for the wake word) and are never used
for chat requests.

Values live in the ``settings`` table under ``secret.<name>`` and are never
returned by any endpoint — only a masked hint (``…abcd``) is exposed. The
``/api/settings`` endpoint filters this prefix out as well.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from . import db

SERVICE_KEYS: Dict[str, Dict[str, str]] = {
    "hf": {
        "label": "Hugging Face token",
        "hint": "Access token (hf_...) from huggingface.co/settings/tokens",
        "used_for": "Image generation and local-model downloads",
    },
    "picovoice": {
        "label": "Picovoice access key",
        "hint": "Access key from console.picovoice.ai",
        "used_for": "Wake-word detection (the word that wakes Jarvis)",
    },
}


def _setting_key(name: str) -> str:
    return f"secret.{name}"


def is_known(name: str) -> bool:
    return name in SERVICE_KEYS


def set_key(name: str, value: Optional[str]) -> bool:
    """Store a service key. An empty value clears it. Unknown names are rejected."""
    if name not in SERVICE_KEYS:
        return False
    value = (value or "").strip()
    if not value:
        delete_key(name)
        return True
    db.set_setting(_setting_key(name), value)
    return True


def get_key(name: str) -> Optional[str]:
    """Raw secret — for internal use only. Never expose this over the API."""
    if name not in SERVICE_KEYS:
        return None
    return db.get_setting(_setting_key(name)) or None


def delete_key(name: str) -> bool:
    if name not in SERVICE_KEYS:
        return False
    db.delete_setting(_setting_key(name))
    return True


def mask(value: Optional[str]) -> str:
    """A safe hint for the UI — mirrors ``llm.mask_key`` (last 4 chars only)."""
    if not value:
        return ""
    tail = value[-4:] if len(value) >= 4 else value
    return f"…{tail}"


def status(name: str) -> Dict[str, object]:
    """Masked status for one service key (safe to send to clients)."""
    meta = SERVICE_KEYS.get(name, {})
    key = get_key(name)
    return {
        "name": name,
        "label": meta.get("label", name),
        "hint": meta.get("hint", ""),
        "used_for": meta.get("used_for", ""),
        "key_set": bool(key),
        "key_hint": mask(key),
    }


def list_keys() -> List[Dict[str, object]]:
    """Masked status for every known service key."""
    return [status(name) for name in SERVICE_KEYS]
