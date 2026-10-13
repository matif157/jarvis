"""Simple task planner/executor."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import get_data_dir
from .logging import get_logger
from .tools import ToolRegistry, get_default_registry

logger = get_logger(__name__)


@dataclass
class TaskStep:
    id: str
    tool: str
    args: Dict[str, Any]
    status: str = "pending"  # pending/running/completed/failed
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class PlanTask:
    id: str
    goal: str
    status: str = "pending"  # pending/running/completed/failed/blocked
    steps: List[TaskStep] = None
    created_at: str = ""
    updated_at: str = ""
    result: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.steps is None:
            self.steps = []
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = datetime.now().isoformat()


class TaskExecutor:
    def __init__(self, registry: Optional[ToolRegistry] = None):
        self.registry = registry or get_default_registry()
        self.tasks_dir = Path(get_data_dir()) / "tasks_exec"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logger

    def _task_path(self, tid: str) -> Path:
        return self.tasks_dir / f"{tid}.json"

    def create_task(self, goal: str, steps: Optional[List[Dict[str, Any]]] = None) -> PlanTask:
        tid = datetime.now().strftime("%Y%m%d%H%M%S%f")
        task = PlanTask(id=tid, goal=goal)
        if steps:
            for i, s in enumerate(steps, 1):
                task.steps.append(
                    TaskStep(
                        id=f"{tid}_s{i}",
                        tool=s["tool"],
                        args=s.get("args", {}),
                    )
                )
        self._save(task)
        self.logger.info(f"Created task {tid}: {goal}")
        return task

    def load(self, tid: str) -> Optional[PlanTask]:
        p = self._task_path(tid)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            task = PlanTask(
                id=data["id"],
                goal=data["goal"],
                status=data["status"],
                created_at=data["created_at"],
                updated_at=data["updated_at"],
                result=data.get("result"),
            )
            for s in data.get("steps", []):
                task.steps.append(TaskStep(**s))
            return task
        except Exception:
            return None

    def _save(self, task: PlanTask) -> None:
        task.updated_at = datetime.now().isoformat()
        data = {
            "id": task.id,
            "goal": task.goal,
            "status": task.status,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "result": task.result,
            "steps": [asdict(s) for s in task.steps],
        }
        self._task_path(task.id).write_text(json.dumps(data, indent=2), encoding="utf-8")

    def execute(self, tid: str, confirm_all: bool = False) -> PlanTask:
        task = self.load(tid)
        if not task:
            raise ValueError(f"task not found: {tid}")
        task.status = "running"
        self._save(task)
        results = []
        blocked = False
        for step in task.steps:
            step.status = "running"
            self._save(task)
            res = self.registry.execute(step.tool, confirm=confirm_all, **step.args)
            if res.success:
                step.status = "completed"
                step.result = res.to_dict()
            else:
                step.status = "failed"
                step.error = res.error
                step.result = res.to_dict()
                if res.meta and res.meta.get("needs_confirmation"):
                    blocked = True
            self._save(task)
            results.append(step.result)
            if blocked:
                break
        if blocked:
            task.status = "blocked"
        elif any(s.status == "failed" for s in task.steps):
            task.status = "failed"
        else:
            task.status = "completed"
        task.result = {"steps": results}
        self._save(task)
        return task
