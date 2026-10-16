"""Phase 13 - Resumable workflows.

A workflow is a named, persisted, multi-step plan that can be started,
paused, resumed (even after the process restarts), inspected and cancelled.
Each step runs a registered tool; state is written to disk after every step,
so a workflow blocked on a confirmation-required action can be resumed later.

Local-first and honest: unknown tools/ids return errors, gated steps report
``needs_confirmation`` instead of running, and results reflect real tool
output (never fabricated).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import get_data_dir
from .logging import get_logger
from .permissions import PermissionManager
from .tools import Tool, ToolRegistry, ToolResult, get_enhanced_registry

logger = get_logger(__name__)

WORKFLOWS_DIR = Path(get_data_dir()) / "workflows"
WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)

# Workflow lifecycle states
WORKFLOW_STATUSES = ("pending", "running", "paused", "blocked", "completed", "failed", "cancelled")
TERMINAL_STATUSES = ("completed", "cancelled")
# States a workflow can be resumed from
RESUMABLE_STATUSES = ("pending", "paused", "blocked", "failed")

# Step lifecycle states
STEP_STATUSES = ("pending", "running", "completed", "failed", "blocked", "skipped")


def _now() -> str:
    return datetime.now().isoformat()


def _new_id(prefix: str = "wf") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass
class WorkflowStep:
    id: str
    tool: str
    args: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    status: str = "pending"
    result: Any = None
    error: Optional[str] = None
    attempts: int = 0
    max_retries: int = 0
    optional: bool = False  # a failed optional step does not fail the workflow
    continue_on_error: bool = False


@dataclass
class Workflow:
    id: str
    name: str
    goal: str = ""
    status: str = "pending"
    steps: List[WorkflowStep] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _now()
        if not self.updated_at:
            self.updated_at = _now()

    def next_step(self) -> Optional[WorkflowStep]:
        """First step that still needs running.

        Completed/skipped steps are done; a failed step that is optional or
        marked ``continue_on_error`` is also considered handled (its failure
        does not halt or restart the workflow).
        """
        for step in self.steps:
            if step.status in ("completed", "skipped"):
                continue
            if step.status == "failed" and (step.optional or step.continue_on_error):
                continue
            return step
        return None

    def summary(self) -> Dict[str, Any]:
        counts: Dict[str, int] = {}
        for s in self.steps:
            counts[s.status] = counts.get(s.status, 0) + 1
        return {
            "id": self.id,
            "name": self.name,
            "goal": self.goal,
            "status": self.status,
            "steps": len(self.steps),
            "step_status": counts,
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
        }


class WorkflowStore:
    """Persist workflows as one JSON file per workflow under data/workflows/."""

    def __init__(self, path: Optional[Path] = None):
        self.dir = Path(path) if path else WORKFLOWS_DIR
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, wf_id: str) -> Path:
        return self.dir / f"{wf_id}.json"

    def save(self, workflow: Workflow) -> None:
        workflow.updated_at = _now()
        data = asdict(workflow)
        tmp = self._path(workflow.id).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        tmp.replace(self._path(workflow.id))

    def load(self, wf_id: str) -> Optional[Workflow]:
        p = self._path(wf_id)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            steps = [WorkflowStep(**s) for s in data.pop("steps", [])]
            return Workflow(steps=steps, **data)
        except Exception as exc:
            logger.warning(f"Failed to load workflow {wf_id}: {exc}")
            return None

    def list(self, status: Optional[str] = None, tag: Optional[str] = None) -> List[Workflow]:
        out: List[Workflow] = []
        for p in sorted(self.dir.glob("wf_*.json")):
            wf = self.load(p.stem)
            if wf is None:
                continue
            if status and wf.status != status:
                continue
            if tag and tag not in wf.tags:
                continue
            out.append(wf)
        return out

    def delete(self, wf_id: str) -> bool:
        p = self._path(wf_id)
        if p.exists():
            p.unlink()
            return True
        return False


def _resolve_path(value: Any, path: List[str]) -> Any:
    cur = value
    for key in path:
        if isinstance(cur, dict):
            cur = cur.get(key)
        elif isinstance(cur, list):
            try:
                cur = cur[int(key)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


def _interpolate(value: Any, workflow: Workflow) -> Any:
    """Resolve ``${...}`` tokens in string args against workflow state."""
    if isinstance(value, dict):
        return {k: _interpolate(v, workflow) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v, workflow) for v in value]
    if not isinstance(value, str) or "${" not in value:
        return value

    # ${goal} / ${context.key} / ${steps.<id>.result[.path]} / ${steps.<id>.status}
    if value == "${goal}":
        return workflow.goal
    if value.startswith("${context.") and value.endswith("}"):
        return workflow.context.get(value[len("${context.") : -1])
    if value.startswith("${steps.") and value.endswith("}"):
        parts = value[len("${steps.") : -1].split(".")
        step = next((s for s in workflow.steps if s.id == parts[0]), None)
        if step is None:
            return None
        if len(parts) >= 2 and parts[1] == "status":
            return step.status
        if len(parts) >= 2 and parts[1] == "result":
            return _resolve_path(step.result, parts[2:])
        return None
    return value


class WorkflowEngine:
    """Create and run resumable workflows with persistent state."""

    def __init__(self, registry: Optional[ToolRegistry] = None, store: Optional[WorkflowStore] = None):
        self.registry = registry or get_enhanced_registry()
        self.store = store or WorkflowStore()
        self.perms = PermissionManager()

    # ------------------------------------------------------------- creation
    def create(
        self,
        name: str,
        steps: List[Dict[str, Any]],
        goal: str = "",
        context: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> Workflow:
        if not name:
            raise ValueError("name is required")
        wf_id = _new_id()
        wf_steps: List[WorkflowStep] = []
        for i, s in enumerate(steps, 1):
            wf_steps.append(
                WorkflowStep(
                    id=s.get("id") or f"step{i}",
                    tool=s["tool"],
                    args=s.get("args", {}),
                    description=s.get("description", ""),
                    max_retries=int(s.get("max_retries", 0)),
                    optional=bool(s.get("optional", False)),
                    continue_on_error=bool(s.get("continue_on_error", False)),
                )
            )
        wf = Workflow(id=wf_id, name=name, goal=goal, steps=wf_steps, context=context or {}, tags=tags or [])
        self.store.save(wf)
        return wf

    def from_goal(self, goal: str, name: str = "") -> Workflow:
        from .planner import Planner

        subtasks = Planner().decompose(goal)
        steps = [
            {"id": st.id, "tool": st.action, "args": st.args, "description": st.description}
            for st in subtasks
        ]
        return self.create(name=name or goal, steps=steps, goal=goal, tags=["planned"])

    def get(self, wf_id: str) -> Optional[Workflow]:
        return self.store.load(wf_id)

    def list(self, status: Optional[str] = None, tag: Optional[str] = None) -> List[Workflow]:
        return self.store.list(status=status, tag=tag)

    def delete(self, wf_id: str) -> bool:
        return self.store.delete(wf_id)

    # ------------------------------------------------------------ lifecycle
    def start(self, wf_id: str, confirm: bool = False) -> Workflow:
        wf = self._require(wf_id)
        if wf.status not in ("pending", "paused", "blocked"):
            raise ValueError(f"workflow {wf_id} cannot be started from status '{wf.status}'")
        return self._run(wf, confirm=confirm)

    def resume(self, wf_id: str, confirm: bool = False) -> Workflow:
        wf = self._require(wf_id)
        if wf.status in TERMINAL_STATUSES:
            raise ValueError(f"workflow {wf_id} is already {wf.status}")
        return self._run(wf, confirm=confirm)

    def pause(self, wf_id: str) -> Workflow:
        wf = self._require(wf_id)
        if wf.status in TERMINAL_STATUSES:
            raise ValueError(f"workflow {wf_id} is already {wf.status}")
        wf.status = "paused"
        self.store.save(wf)
        return wf

    def cancel(self, wf_id: str) -> Workflow:
        wf = self._require(wf_id)
        wf.status = "cancelled"
        wf.finished_at = _now()
        self.store.save(wf)
        return wf

    # ------------------------------------------------------------- internal
    def _require(self, wf_id: str) -> Workflow:
        wf = self.store.load(wf_id)
        if wf is None:
            raise ValueError(f"workflow not found: {wf_id}")
        return wf

    def _run(self, wf: Workflow, confirm: bool) -> Workflow:
        if wf.status not in ("running",):
            wf.status = "running"
        if not wf.started_at:
            wf.started_at = _now()
        wf.error = None
        self.store.save(wf)

        while True:
            step = wf.next_step()
            if step is None:
                wf.status = "completed"
                wf.finished_at = _now()
                self.store.save(wf)
                return wf

            step = self._run_step(wf, step, confirm)
            if step.status == "blocked":
                wf.status = "blocked"
                self.store.save(wf)
                return wf
            if step.status == "failed" and not (step.optional or step.continue_on_error):
                wf.status = "failed"
                wf.error = f"step {step.id} failed: {step.error}"
                wf.finished_at = _now()
                self.store.save(wf)
                return wf
            if step.status == "failed" and step.optional:
                step.status = "skipped"
                self.store.save(wf)

    def _run_step(self, wf: Workflow, step: WorkflowStep, confirm: bool) -> WorkflowStep:
        resolved = _interpolate(step.args, wf)
        step.status = "running"
        self.store.save(wf)

        last_error: Optional[str] = None
        for attempt in range(step.max_retries + 1):
            step.attempts += 1
            res: ToolResult = self.registry.execute(step.tool, confirm=confirm, **resolved)
            if res.success:
                step.status = "completed"
                step.result = res.result
                step.error = None
                self.store.save(wf)
                return step
            if res.meta and res.meta.get("needs_confirmation"):
                step.status = "blocked"
                step.error = res.error
                self.store.save(wf)
                return step
            last_error = res.error
            self.store.save(wf)

        step.status = "failed"
        step.error = last_error
        self.store.save(wf)
        return step


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
def _steps_payload(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return steps


class WorkflowCreateTool(Tool):
    name = "workflow.create"
    description = "Create a resumable workflow from a list of tool steps"
    permissions = ["workflow.write"]

    def run(self, workflow_name: str = "", steps: Optional[List[Dict[str, Any]]] = None, goal: str = "", context: Optional[Dict[str, Any]] = None, tags: Optional[List[str]] = None) -> ToolResult:
        if not workflow_name:
            return ToolResult(success=False, error="workflow_name is required", tool=self.name)
        if not steps:
            return ToolResult(success=False, error="steps are required (list of {tool, args})", tool=self.name)
        engine = WorkflowEngine()
        try:
            wf = engine.create(name=workflow_name, steps=steps, goal=goal, context=context, tags=tags)
        except Exception as exc:
            return ToolResult(success=False, error=str(exc), tool=self.name)
        return ToolResult(success=True, result=wf.summary(), tool=self.name)


class WorkflowFromGoalTool(Tool):
    name = "workflow.from_goal"
    description = "Create a resumable workflow by planning a natural-language goal"
    permissions = ["workflow.write"]

    def run(self, goal: str, workflow_name: str = "") -> ToolResult:
        if not goal:
            return ToolResult(success=False, error="goal is required", tool=self.name)
        engine = WorkflowEngine()
        wf = engine.from_goal(goal, name=workflow_name)
        return ToolResult(success=True, result=wf.summary(), tool=self.name)


class WorkflowListTool(Tool):
    name = "workflow.list"
    description = "List workflows, optionally filtered by status or tag"
    permissions = ["workflow.read"]

    def run(self, status: str = "", tag: str = "") -> ToolResult:
        engine = WorkflowEngine()
        items = [wf.summary() for wf in engine.list(status=status or None, tag=tag or None)]
        return ToolResult(success=True, result={"count": len(items), "workflows": items}, tool=self.name)


class WorkflowGetTool(Tool):
    name = "workflow.get"
    description = "Get a workflow's full state including each step"
    permissions = ["workflow.read"]

    def run(self, workflow_id: str = "") -> ToolResult:
        if not workflow_id:
            return ToolResult(success=False, error="workflow_id is required", tool=self.name)
        wf = WorkflowEngine().get(workflow_id)
        if wf is None:
            return ToolResult(success=False, error=f"workflow not found: {workflow_id}", tool=self.name)
        data = asdict(wf)
        return ToolResult(success=True, result=data, tool=self.name)


class WorkflowStartTool(Tool):
    name = "workflow.start"
    description = "Start a pending workflow (runs allowed steps; gated steps block until resumed)"
    permissions = ["workflow.write"]

    def run(self, workflow_id: str = "") -> ToolResult:
        if not workflow_id:
            return ToolResult(success=False, error="workflow_id is required", tool=self.name)
        engine = WorkflowEngine()
        try:
            wf = engine.start(workflow_id, confirm=False)
        except Exception as exc:
            return ToolResult(success=False, error=str(exc), tool=self.name)
        return ToolResult(success=True, result=wf.summary(), tool=self.name)


class WorkflowResumeTool(Tool):
    name = "workflow.resume"
    description = "Resume a paused/blocked/failed workflow, authorizing its remaining steps"
    permissions = ["workflow.run"]

    def run(self, workflow_id: str = "") -> ToolResult:
        if not workflow_id:
            return ToolResult(success=False, error="workflow_id is required", tool=self.name)
        engine = WorkflowEngine()
        try:
            wf = engine.resume(workflow_id, confirm=True)
        except Exception as exc:
            return ToolResult(success=False, error=str(exc), tool=self.name)
        return ToolResult(success=True, result=wf.summary(), tool=self.name)


class WorkflowPauseTool(Tool):
    name = "workflow.pause"
    description = "Pause a workflow so it can be resumed later"
    permissions = ["workflow.write"]

    def run(self, workflow_id: str = "") -> ToolResult:
        if not workflow_id:
            return ToolResult(success=False, error="workflow_id is required", tool=self.name)
        try:
            wf = WorkflowEngine().pause(workflow_id)
        except Exception as exc:
            return ToolResult(success=False, error=str(exc), tool=self.name)
        return ToolResult(success=True, result=wf.summary(), tool=self.name)


class WorkflowCancelTool(Tool):
    name = "workflow.cancel"
    description = "Cancel a workflow (terminal)"
    permissions = ["workflow.write"]

    def run(self, workflow_id: str = "") -> ToolResult:
        if not workflow_id:
            return ToolResult(success=False, error="workflow_id is required", tool=self.name)
        try:
            wf = WorkflowEngine().cancel(workflow_id)
        except Exception as exc:
            return ToolResult(success=False, error=str(exc), tool=self.name)
        return ToolResult(success=True, result=wf.summary(), tool=self.name)


class WorkflowDeleteTool(Tool):
    name = "workflow.delete"
    description = "Delete a workflow from storage"
    permissions = ["workflow.write"]

    def run(self, workflow_id: str = "") -> ToolResult:
        if not workflow_id:
            return ToolResult(success=False, error="workflow_id is required", tool=self.name)
        ok = WorkflowEngine().delete(workflow_id)
        if not ok:
            return ToolResult(success=False, error=f"workflow not found: {workflow_id}", tool=self.name)
        return ToolResult(success=True, result={"deleted": workflow_id}, tool=self.name)


def get_workflow_tools() -> List[Tool]:
    """Return all Phase 13 resumable-workflow tools."""
    return [
        WorkflowCreateTool(),
        WorkflowFromGoalTool(),
        WorkflowListTool(),
        WorkflowGetTool(),
        WorkflowStartTool(),
        WorkflowResumeTool(),
        WorkflowPauseTool(),
        WorkflowCancelTool(),
        WorkflowDeleteTool(),
    ]


def get_workflow_tools_for_registry() -> List[Tool]:
    return get_workflow_tools()
