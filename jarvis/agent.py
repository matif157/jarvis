"""Autonomous agent with planning loop."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from .engine_tasks import TaskExecutor
from .logging import get_logger
from .planner import Planner
from .tools import get_enhanced_registry

logger = get_logger(__name__)


class Agent:
    def __init__(self, registry=None):
        self.registry = registry or get_enhanced_registry()
        self.executor = TaskExecutor(self.registry)
        self.planner = Planner()
        self.max_retries = 2
        self.logger = logger

    def run_goal(self, goal: str, auto_confirm: bool = False) -> Dict[str, Any]:
        subs = self.planner.decompose(goal)
        steps = [{"tool": s.action, "args": s.args} for s in subs]
        task = self.executor.create_task(goal, steps=steps)
        self.executor.execute(task.id, confirm_all=auto_confirm)
        task = self.executor.load(task.id)
        return {
            "task_id": task.id,
            "goal": task.goal,
            "status": task.status,
            "steps": len(task.steps),
            "result": task.result,
        }

    async def run_goal_async(self, goal: str, auto_confirm: bool = False) -> Dict[str, Any]:
        return self.run_goal(goal, auto_confirm)
