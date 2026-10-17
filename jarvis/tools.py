"""Tool registry and base classes for Jarvis."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import datetime
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


# ---------------------------------------------------------------------------
# Built-in tools
# ------------------------------------------------------------- time / echo

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


# ------------------------------------------------------------- tasks
class TaskAddTool(Tool):
    name = "task.add"
    description = "Create a new task with title, optional description and priority"
    permissions = ["task.write"]

    def run(self, title: str, description: str = "", priority: str = "medium", due_date: str = "") -> ToolResult:
        from . import tasks

        if not title:
            return ToolResult(success=False, error="title is required", tool=self.name)
        task = tasks.TaskManager().add_task(title=title, description=description, priority=priority)
        if due_date:
            tasks.db.set_setting(f"task.due_date.{task.id}", due_date)
        return ToolResult(success=True, result={"id": task.id, "title": task.title, "status": task.status}, tool=self.name)


class TaskListTool(Tool):
    name = "task.list"
    description = "List tasks, optionally filtered by status"
    permissions = ["task.read"]

    def run(self, status: str = None) -> ToolResult:
        from . import tasks

        tasks_list = tasks.TaskManager().list_tasks(status=status)
        return ToolResult(success=True, result=tasks_list, tool=self.name)


class TaskCompleteTool(Tool):
    name = "task.complete"
    description = "Mark a task as completed"
    permissions = ["task.write"]

    def run(self, task_id: str) -> ToolResult:
        from . import tasks

        success = tasks.TaskManager().complete_task(task_id)
        if success:
            return ToolResult(success=True, result={"id": task_id, "status": "completed"}, tool=self.name)
        return ToolResult(success=False, error="task not found", tool=self.name)


class TaskReopenTool(Tool):
    name = "task.reopen"
    description = "Reopen a completed task"
    permissions = ["task.write"]

    def run(self, task_id: str) -> ToolResult:
        from datetime import datetime

        from . import tasks

        conn = tasks.db.connect()
        conn.execute(
            "UPDATE tasks SET status='pending', updated_at=? WHERE task_id=?",
            (datetime.now().isoformat(), task_id),
        )
        conn.commit()
        conn.close()
        return ToolResult(success=True, result={"id": task_id, "status": "pending"}, tool=self.name)


class TaskCancelTool(Tool):
    name = "task.cancel"
    description = "Cancel a task (set status to cancelled)"
    permissions = ["task.write"]

    def run(self, task_id: str) -> ToolResult:
        from datetime import datetime

        from . import db

        conn = db.connect()
        conn.execute("UPDATE tasks SET status='cancelled', updated_at=? WHERE task_id=?", (datetime.now().isoformat(), task_id))
        conn.commit()
        conn.close()
        return ToolResult(success=True, result={"id": task_id, "status": "cancelled"}, tool=self.name)


class NoteAddTool(Tool):
    name = "note.add"
    description = "Create a new note with content and optional tags"
    permissions = ["note.write"]

    def run(self, content: str, tags: List[str] = None) -> ToolResult:
        from . import db
        import uuid

        note_id = str(uuid.uuid4())
        db.add_note_db(note_id=note_id, content=content, tags=tags or [])
        return ToolResult(success=True, result={"id": note_id, "content": content}, tool=self.name)


class NoteListTool(Tool):
    name = "note.list"
    description = "List all notes, optionally filtered by tag"
    permissions = ["note.read"]

    def run(self, tag: str = None) -> ToolResult:
        from . import db

        notes = db.get_notes_db()
        if tag:
            notes = [n for n in notes if tag in n.get("tags", [])]
        return ToolResult(success=True, result=notes, tool=self.name)


class NoteSearchTool(Tool):
    name = "note.search"
    description = "Search notes by keyword in content or tags"
    permissions = ["note.read"]

    def run(self, keyword: str) -> ToolResult:
        from . import db

        notes = db.get_notes_db()
        results = [
            n
            for n in notes
            if keyword.lower() in n.get("content", "").lower() or keyword.lower() in [k.lower() for k in n.get("tags", [])]
        ]
        return ToolResult(success=True, result=results, tool=self.name)


class NoteReadTool(Tool):
    name = "note.read"
    description = "Read a note by ID"
    permissions = ["note.read"]

    def run(self, note_id: str) -> ToolResult:
        from . import db

        notes = db.get_notes_db()
        for n in notes:
            if n.get("id") == note_id:
                return ToolResult(success=True, result=n, tool=self.name)
        return ToolResult(success=False, error="note not found", tool=self.name)


class MemoryRememberTool(Tool):
    name = "memory.remember"
    description = "Store a key-value fact in memory"
    permissions = ["memory.write"]

    def run(self, key: str, value: Any) -> ToolResult:
        from . import db

        db.remember_db(key, value)
        return ToolResult(success=True, result={"key": key, "value": value}, tool=self.name)


class MemoryRecallTool(Tool):
    name = "memory.recall"
    description = "Retrieve a fact from memory by key"
    permissions = ["memory.read"]

    def run(self, key: str) -> ToolResult:
        from . import db

        value = db.recall_db(key)
        if value is not None:
            return ToolResult(success=True, result={"key": key, "value": value}, tool=self.name)
        return ToolResult(success=False, error="key not found", tool=self.name)


class MemoryListTool(Tool):
    name = "memory.list"
    description = "List all stored memory facts"
    permissions = ["memory.read"]

    def run(self) -> ToolResult:
        from . import db

        all_m = db.get_all_memory_db()
        return ToolResult(success=True, result=all_m, tool=self.name)


class MemoryForgetTool(Tool):
    name = "memory.forget"
    description = "Forget a fact by key"
    permissions = ["memory.write"]

    def run(self, key: str) -> ToolResult:
        from . import db

        db.forget_db(key)
        return ToolResult(success=True, result={"key": key, "forgot": True}, tool=self.name)


class FindFilesTool(Tool):
    name = "fs.find"
    description = "Find files matching a filename pattern in allowed directories"
    permissions = ["file.read"]

    def run(self, pattern: str, directory: str = ".") -> ToolResult:
        import fnmatch
        from pathlib import Path

        from . import security

        dir_path = Path(directory).expanduser().resolve()
        if not security.is_path_safe(str(dir_path)):
            return ToolResult(success=False, error="directory not allowed", tool=self.name)

        matches = []
        if dir_path.is_dir():
            for item in sorted(dir_path.iterdir())[:200]:
                try:
                    if fnmatch.fnmatch(item.name, pattern):
                        stat = item.stat()
                        matches.append(
                            {
                                "name": item.name,
                                "path": str(item),
                                "size": stat.st_size,
                                "modified": stat.st_mtime,
                                "is_dir": item.is_dir(),
                            }
                        )
                except Exception:
                    continue

        return ToolResult(success=True, result=matches, tool=self.name)


class EchoTool(Tool):  # noqa: F811 (single canonical definition)
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

    # Filesystem tools
    try:
        from . import tools_fs

        reg.register(tools_fs.ListFilesTool())
        reg.register(tools_fs.ReadFileTool())
    except Exception:
        pass

    # Productivity tools (tasks, notes, memory) — defined in this module
    for tool in (
        TaskAddTool(),
        TaskListTool(),
        TaskCompleteTool(),
        TaskReopenTool(),
        TaskCancelTool(),
        NoteAddTool(),
        NoteListTool(),
        NoteSearchTool(),
        NoteReadTool(),
        MemoryRememberTool(),
        MemoryRecallTool(),
        MemoryListTool(),
        MemoryForgetTool(),
    ):
        reg.register(tool)

    # File discovery
    reg.register(FindFilesTool())

    # Web search / research (Phase 6)
    try:
        from . import web_search

        for tool in web_search.get_web_tools():
            reg.register(tool)
    except Exception:
        pass

    # Safe macOS actions (Phase 5)
    try:
        from . import macos_actions

        reg.register(macos_actions.OpenAppTool())
        reg.register(macos_actions.OpenURLTool())
        reg.register(macos_actions.RevealInFinderTool())
        reg.register(macos_actions.CreateFileTool())
    except Exception:
        pass

    # Google Drive (Phase 7)
    try:
        from . import google_drive

        reg.register(google_drive.DriveConnectTool())
        reg.register(google_drive.DriveDisconnectTool())
        reg.register(google_drive.DriveStatusTool())
        reg.register(google_drive.DriveSearchTool())
        reg.register(google_drive.DriveGetFileTool())
        reg.register(google_drive.DriveReadFileTool())
        reg.register(google_drive.DriveListFolderTool())
    except Exception:
        pass

    # Career / resume (Phase 8)
    try:
        from . import career

        reg.register(career.ResumeParseTool())
        reg.register(career.ResumeListTool())
        reg.register(career.ResumeGetTool())
        reg.register(career.ResumeDeleteTool())
        reg.register(career.CareerProfileTool())
        reg.register(career.ResumeSearchTool())
    except Exception:
        pass

    # Email (Phase 9)
    try:
        from . import email

        reg.register(email.EmailConnectTool())
        reg.register(email.EmailDisconnectTool())
        reg.register(email.EmailStatusTool())
        reg.register(email.EmailSearchTool())
        reg.register(email.EmailReadTool())
        reg.register(email.EmailSendTool())
        reg.register(email.EmailListFoldersTool())
    except Exception:
        pass

    # Jobs (Phase 10)
    try:
        from . import jobs

        for tool in jobs.get_job_tools():
            reg.register(tool)
    except Exception:
        pass

    # Voice (Phase 11)
    try:
        from . import voice

        for tool in voice.get_voice_tools():
            reg.register(tool)
    except Exception:
        pass

    # Resumable workflows (Phase 13)
    try:
        from . import workflows

        for tool in workflows.get_workflow_tools():
            reg.register(tool)
    except Exception:
        pass

    # Atif bridge (Phase 14)
    try:
        from . import atif_client

        for tool in atif_client.get_atif_tools():
            reg.register(tool)
    except Exception:
        pass

    # IoT / smart devices (Phase 14)
    try:
        from . import iot

        for tool in iot.get_iot_tools():
            reg.register(tool)
    except Exception:
        pass

    return reg
