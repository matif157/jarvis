"""Goal decomposition and planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from .logging import get_logger

logger = get_logger(__name__)


@dataclass
class SubTask:
    id: str
    description: str
    action: str
    args: Dict[str, Any]


class Planner:
    def __init__(self):
        self.logger = logger

    def decompose(self, goal: str) -> List[SubTask]:
        goal_l = goal.lower()
        tasks: List[SubTask] = []
        if "time" in goal_l:
            tasks.append(SubTask(id="t1", description="Get current time", action="time.now", args={}))
        if "find" in goal_l or "list" in goal_l:
            tasks.append(SubTask(id="f1", description="List files in Downloads", action="fs.list", args={"directory": "~/Downloads"}))
        if not tasks:
            tasks.append(SubTask(id="e1", description="Echo goal", action="echo", args={"text": f"Planning for: {goal}"}))
        return tasks
