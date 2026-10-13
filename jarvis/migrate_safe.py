"""Safe migration utilities with backups."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from .config import get_data_dir


def backup_json_files() -> List[str]:
    backups = []
    data_dir = Path(get_data_dir())
    for name in ("notes.json", "tasks.json", "memory.json"):
        p = data_dir / name
        if p.exists():
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            bp = data_dir / f"{name}.{ts}.bak"
            try:
                shutil.copy2(p, bp)
                backups.append(str(bp))
            except Exception:
                pass
    return backups


def verify_counts(original: Dict[str, int], migrated: Dict[str, int]) -> bool:
    for k in set(original) | set(migrated):
        if migrated.get(k, 0) < original.get(k, 0):
            return False
    return True
