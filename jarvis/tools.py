"""Tool registry and base classes for Jarvis."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from .logging import get_logger
from .permissions import PermissionManager

logger = get_logger(__name__)


@dataclass
class ToolResult:
    success: bool
    result: Any = None
    error: Optional[str] = None
    tool: str = ""
    meta: Dict[str, Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "tool": self.tool,
            "meta": self.meta or {},
        }


class Tool:
    name: str = "base"
    description: str = ""
    permissions: List[str] = []
    requires_confirmation: bool = False

    def __init__(self):
        self.perms = PermissionManager()

    def validate(self, **kwargs) -> bool:
        return True

    def run(self, **kwargs) -> ToolResult:
        raise NotImplementedError


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self.perms = PermissionManager()
        self.logger = get_logger("tool_registry")

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        self.logger.debug(f"Registered tool: {tool.name}")

    def register_function(self, name: str, func: Callable, description: str = "", permissions: List[str] = None) -> None:
        permissions = permissions or []

        class FuncTool(Tool):
            def __init__(self):
                super().__init__()
                self.name = name
                self.description = description
                self.permissions = permissions

            def run(self, **kwargs) -> ToolResult:
                try:
                    sig = inspect.signature(func)
                    filtered = {k: v for k, v in kwargs.items() if k in sig.parameters}
                    res = func(**filtered)
                    return ToolResult(success=True, result=res, tool=self.name)
                except Exception as e:
                    return ToolResult(success=False, error=str(e), tool=self.name)

        self.register(FuncTool())

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "permissions": t.permissions,
            }
            for t in self._tools.values()
        ]

    def execute(self, name: str, confirm: bool = False, **kwargs) -> ToolResult:
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(success=False, error=f"unknown tool: {name}", tool=name)
        for p in tool.permissions:
            if not self.perms.is_allowed(p):
                return ToolResult(success=False, error=f"permission denied: {p}", tool=name)
            if self.perms.needs_confirmation(p) and not confirm:
                return ToolResult(
                    success=False,
                    error=f"confirmation required for {p}",
                    tool=name,
                    meta={"needs_confirmation": True, "permission": p},
                )
        if not tool.validate(**kwargs):
            return ToolResult(success=False, error="validation failed", tool=name)
        try:
            res = tool.run(**kwargs)
            return res
        except Exception as e:
            logger.error(f"Tool {name} failed: {e}")
            return ToolResult(success=False, error=str(e), tool=name)


# Built-in tools
class TimeTool(Tool):
    name = "time.now"
    description = "Get current time"
    permissions = []

    def run(self, **kwargs) -> ToolResult:
        from datetime import datetime

        return ToolResult(success=True, result=datetime.now().isoformat(), tool=self.name)


class EchoTool(Tool):
    name = "echo"
    description = "Echo text back"
    permissions = []

    def run(self, text: str = "", **kwargs) -> ToolResult:
        return ToolResult(success=True, result=text, tool=self.name)


def _register_defaults(reg: ToolRegistry) -> None:
    reg.register(TimeTool())
    reg.register(EchoTool())


def get_default_registry() -> ToolRegistry:
    reg = ToolRegistry()
    _register_defaults(reg)
    return reg


def get_enhanced_registry() -> ToolRegistry:
    reg = get_default_registry()
    try:
        from . import tools_fs

        reg.register(tools_fs.ListFilesTool())
        reg.register(tools_fs.ReadFileTool())
    except Exception:
        pass
    return reg
