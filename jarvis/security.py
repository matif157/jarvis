"""Security helpers for safe operations."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

SAFE_BASES = [
    Path.home() / "Documents",
    Path.home() / "Downloads",
    Path.home() / "Desktop",
    Path.home(),
]


def is_path_safe(path: str, allowed_bases: Optional[List[Path]] = None) -> bool:
    bases = allowed_bases or SAFE_BASES
    try:
        p = Path(path).expanduser().resolve()
        for b in bases:
            try:
                p.relative_to(b.resolve())
                return True
            except Exception:
                continue
        # also allow inside jarvis project
        proj = Path(__file__).parent.parent.resolve()
        try:
            p.relative_to(proj)
            return True
        except Exception:
            pass
        return False
    except Exception:
        return False
