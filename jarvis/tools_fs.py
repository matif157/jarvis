"""File system tools with permission checks."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

from .permissions import PermissionManager
from .tools import Tool, ToolResult


def _expand(path: str) -> Path:
    return Path(path).expanduser().resolve()


def _safe(path: Path, perms: PermissionManager) -> bool:
    # basic check - allow common dirs; respect permissions model
    return True


class ListFilesTool(Tool):
    name = "fs.list"
    description = "List files in a directory"
    permissions = ["file.read"]

    def run(self, directory: str = ".", **kwargs) -> ToolResult:
        try:
            p = _expand(directory)
            from . import security
            if not security.is_path_safe(str(p)):
                return ToolResult(success=False, error="path not allowed by security policy", tool=self.name)
            if not p.exists() or not p.is_dir():
                return ToolResult(success=False, error="not a directory", tool=self.name)
            items = []
            for f in sorted(p.iterdir())[:100]:
                items.append({"name": f.name, "is_dir": f.is_dir(), "size": f.stat().st_size if f.exists() else 0})
            return ToolResult(success=True, result=items, tool=self.name)
        except Exception as e:
            return ToolResult(success=False, error=str(e), tool=self.name)


class ReadFileTool(Tool):
    name = "fs.read"
    description = "Read text from a file"
    permissions = ["file.read"]

    def run(self, path: str = "", max_chars: int = 4000, **kwargs) -> ToolResult:
        try:
            p = _expand(path)
            from . import security
            if not security.is_path_safe(str(p)):
                return ToolResult(success=False, error="path not allowed by security policy", tool=self.name)
            if not p.exists() or not p.is_file():
                return ToolResult(success=False, error="not a file", tool=self.name)
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except UnicodeError:
                text = p.read_text(errors="replace")
            if len(text) > max_chars:
                text = text[:max_chars] + f"\n... (truncated {len(text)-max_chars} chars)"
            return ToolResult(success=True, result=text, tool=self.name)
        except Exception as e:
            return ToolResult(success=False, error=str(e), tool=self.name)
