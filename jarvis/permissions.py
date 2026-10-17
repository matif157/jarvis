"""Simple permission model for Jarvis tools and actions."""

from __future__ import annotations

import fnmatch
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set

from .config import get_config_dir


DEFAULT_ALLOWLIST = {
    "file.read": ["Documents/*", "Downloads/*", "Desktop/*", "~/*"],
    "file.write": ["Documents/*", "Downloads/*", "Desktop/*", "~/*"],
    "file.delete": [],
    "shell.run": [],
    "web.search": ["*"],
    "web.research": ["*"],
    "note.read": ["*"],
    "note.write": ["*"],
    "task.read": ["*"],
    "task.write": ["*"],
    "memory.read": ["*"],
    "memory.write": ["*"],
    "email.connect": ["*"],
    "email.read": ["*"],
    "email.send": [],
    "app.open": ["*"],
    "system.configure": [],
    "drive.access": ["*"],
    "drive.read": ["*"],
    "resume.parse": ["*"],
    "resume.read": ["*"],
    "resume.write": ["*"],
    "career.read": ["*"],
    "career.write": ["*"],
    "job.read": ["*"],
    "job.write": ["*"],
    "job.apply": [],
    "voice.read": ["*"],
    "voice.speak": ["*"],
    "voice.listen": [],
    "workflow.read": ["*"],
    "workflow.write": ["*"],
    "workflow.run": [],
    "atif.read": ["*"],
    "atif.ask": ["*"],
    "atif.config": ["*"],
    "iot.read": ["*"],
    "iot.write": ["*"],
    "iot.control": [],
}


def _pattern_variants(pattern: str) -> Set[str]:
    """Expand a single allowlist pattern into concrete path globs.

    Relative patterns (e.g. ``Documents/*``) are interpreted relative to the
    user's home directory, matching how they are written in the default
    allowlist.
    """
    variants: Set[str] = set()
    expanded = os.path.expanduser(pattern)
    variants.add(expanded)
    if not os.path.isabs(expanded):
        variants.add(os.path.join(os.path.expanduser("~"), expanded))
    return variants


def _matches(resource: str, patterns: List[str]) -> bool:
    try:
        target = str(Path(resource).expanduser().resolve())
    except Exception:
        target = os.path.expanduser(str(resource))
    for pattern in patterns:
        for candidate in _pattern_variants(pattern):
            if fnmatch.fnmatch(target, candidate) or target == candidate:
                return True
    return False


@dataclass
class Permissions:
    allow: Dict[str, List[str]]
    ask_first: Set[str]
    deny: Set[str]


class PermissionManager:
    def __init__(self):
        self.config_path = Path(get_config_dir()) / "permissions.json"
        self._load()

    def _load(self) -> None:
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                self.allow = data.get("allow", DEFAULT_ALLOWLIST)
                self.ask_first = set(data.get("ask_first", []))
                self.deny = set(data.get("deny", []))
                return
            except Exception:
                pass
        self.allow = DEFAULT_ALLOWLIST.copy()
        self.ask_first = set()
        self.deny = set()
        self._save()

    def _save(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "allow": self.allow,
            "ask_first": sorted(self.ask_first),
            "deny": sorted(self.deny),
        }
        self.config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def is_allowed(self, action: str, resource: Optional[str] = None) -> bool:
        """Return whether ``action`` (a permission scope) is allowed.

        When ``resource`` (e.g. a path) is given, the scope's allowlist patterns
        are enforced: the resource must match at least one pattern. When no
        resource is given the call only checks ``deny`` plus scope presence, so
        existing scope-only callers (and confirmation-gated scopes) keep working.
        """
        if action in self.deny:
            return False
        patterns = self.allow.get(action)
        if patterns is None:
            # Unknown/unconfigured scope: not restricted (backward compatible).
            return True
        if resource is None:
            return True
        return _matches(str(resource), patterns)

    def needs_confirmation(self, action: str) -> bool:
        if action in self.deny:
            return False
        if action in self.ask_first:
            return True
        # Destructive defaults
        if action in ("file.delete", "system.configure", "email.send", "job.apply", "voice.listen", "workflow.run", "iot.control"):
            return True
        return False

    def grant(self, action: str, patterns: Optional[List[str]] = None) -> None:
        if patterns:
            self.allow.setdefault(action, []).extend(patterns)
        if action in self.deny:
            self.deny.discard(action)
        self._save()

    def deny_action(self, action: str) -> None:
        self.deny.add(action)
        self.ask_first.discard(action)
        self._save()

    def require_confirmation(self, action: str) -> None:
        self.ask_first.add(action)
        self._save()
