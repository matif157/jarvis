"""Task management for Jarvis"""

import json
import os
import uuid
from datetime import datetime
from typing import List, Dict, Any
from dataclasses import dataclass, asdict


@dataclass
class Task:
    id: str
    title: str
    description: str = ""
    status: str = "pending"  # pending, in_progress, completed
    priority: str = "medium"  # low, medium, high
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TaskManager:
    """Manage tasks locally"""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.tasks_file = os.path.join(data_dir, "tasks.json")

    def add_task(self, title: str, description: str = "", priority: str = "medium") -> Task:
        task = Task(id=str(uuid.uuid4()), title=title, description=description, priority=priority)
        tasks = self._load()
        tasks.append(task.to_dict())
        self._save(tasks)
        return task

    def list_tasks(self, status: str = None) -> List[Dict[str, Any]]:
        tasks = self._load()
        if status:
            tasks = [t for t in tasks if t["status"] == status]
        return tasks

    def complete_task(self, task_id: str) -> bool:
        tasks = self._load()
        for task in tasks:
            if task["id"] == task_id:
                task["status"] = "completed"
                task["updated_at"] = datetime.now().isoformat()
                self._save(tasks)
                return True
        return False

    def _load(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.tasks_file):
            return []
        try:
            with open(self.tasks_file, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self, tasks: List[Dict[str, Any]]):
        with open(self.tasks_file, "w") as f:
            json.dump(tasks, f, indent=2)
