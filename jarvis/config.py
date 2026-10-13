"""Configuration for Jarvis"""

import os
from pathlib import Path

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("JARVIS_DATA_DIR", BASE_DIR / "data"))
CONFIG_DIR = Path(os.getenv("JARVIS_CONFIG_DIR", BASE_DIR / "config"))
WEB_DIR = BASE_DIR / "web"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# Server settings
HOST = os.getenv("JARVIS_HOST", "127.0.0.1")
PORT = int(os.getenv("JARVIS_PORT", "8771"))

# Atif Assistant bridge
ATIF_URL = os.getenv("JARVIS_ATIF_URL", "http://127.0.0.1:8770")

# Provider configuration
def _provider_order() -> list:
    raw = os.getenv("JARVIS_PROVIDERS", "groq,gemini,openrouter,ollama")
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


PROVIDER_ORDER = _provider_order()

PROVIDER_ENV_KEYS = {
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ollama": "OLLAMA_API_KEY",
}

MODEL_DEFAULTS = {
    "groq": os.getenv("JARVIS_GROQ_MODEL", "openai/gpt-oss-120b"),
    "gemini": os.getenv("JARVIS_GEMINI_MODEL", "gemini-2.0-flash"),
    "openrouter": os.getenv("JARVIS_OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free"),
    "ollama": os.getenv("JARVIS_OLLAMA_MODEL", "llama3.2:1b"),
}

PROVIDER_LABELS = {
    "groq": "Groq",
    "gemini": "Gemini",
    "openrouter": "OpenRouter",
    "ollama": "Local / Ollama",
}


def get_data_dir() -> str:
    return str(DATA_DIR)


def get_config_dir() -> str:
    return str(CONFIG_DIR)


def get_web_dir() -> str:
    return str(WEB_DIR)


def validate_config() -> None:
    """Basic sanity checks for configuration."""
    data_dir = Path(DATA_DIR)
    if not data_dir.exists() or not data_dir.is_dir():
        data_dir.mkdir(parents=True, exist_ok=True)
    cfg_dir = Path(CONFIG_DIR)
    if not cfg_dir.exists() or not cfg_dir.is_dir():
        cfg_dir.mkdir(parents=True, exist_ok=True)
    web_dir = Path(WEB_DIR)
    if not web_dir.exists():
        # Not fatal, web UI might not be needed.
        pass
