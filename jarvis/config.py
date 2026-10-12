"""Configuration for Jarvis"""

import os
from pathlib import Path

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = os.getenv("JARVIS_DATA_DIR", BASE_DIR / "data")
CONFIG_DIR = os.getenv("JARVIS_CONFIG_DIR", BASE_DIR / "config")

# Ensure directories exist
Path(DATA_DIR).mkdir(exist_ok=True)
Path(CONFIG_DIR).mkdir(exist_ok=True)


def get_data_dir() -> str:
    return str(DATA_DIR)


def get_config_dir() -> str:
    return str(CONFIG_DIR)
