"""Task management for Jarvis - SQLite backed."""

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, List

from . import db


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
    """Manage tasks locally in SQLite."""

    def __init__(self, data_dir: str = None):
        db.init_db()

    def add_task(self, title: str, description: str = "", priority: str = "medium") -> Task:
        task = Task(id=str(uuid.uuid4()), title=title, description=description, priority=priority)
        db.add_task_db(
            task.id, task.title, task.description, task.status, task.priority,
            task.created_at, task.updated_at,
        )
        return task

    def list_tasks(self, status: str = None) -> List[Dict[str, Any]]:
        tasks = db.get_tasks_db()
        if status:
            tasks = [t for t in tasks if t["status"] == status]
        return tasks

    def complete_task(self, task_id: str) -> bool:
        return db.complete_task_db(task_id)
