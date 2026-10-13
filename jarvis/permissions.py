"""Simple permission model for Jarvis tools and actions."""

from __future__ import annotations

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
    "email.send": [],
    "app.open": ["*"],
    "system.configure": [],
}


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

    def is_allowed(self, action: str) -> bool:
        if action in self.deny:
            return False
        return True

    def needs_confirmation(self, action: str) -> bool:
        if action in self.deny:
            return False
        if action in self.ask_first:
            return True
        # Destructive defaults
        if action in ("file.delete", "system.configure", "email.send"):
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
