"""Safe migration utilities with backups."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List

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

def restore_latest_backup(name: str) -> Optional[str]:
    data_dir = Path(get_data_dir())
    candidates = []
    pattern = f"{name}.*.bak"
    for p in data_dir.glob(pattern):
        try:
            candidates.append((p.stat().st_mtime, p))
        except Exception:
            continue
    if not candidates:
        return None
    best = sorted(candidates, key=lambda x: x[0], reverse=True)[0][1]
    target = data_dir / name
    try:
        shutil.copy2(best, target)
        return str(best)
    except Exception:
        return None


def list_backups() -> List[str]:
    data_dir = Path(get_data_dir())
    res = []
    for p in data_dir.glob("*.bak"):
        res.append(str(p))
    return sorted(res)

