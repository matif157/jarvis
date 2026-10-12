"""Migrate legacy JSON data files into the SQLite database."""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from . import db
from .config import get_data_dir


def _read_json(name: str) -> Any:
    path = os.path.join(get_data_dir(), name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None


def migrate(remove_json: bool = False) -> Dict[str, int]:
    """Import notes.json, tasks.json and memory.json into SQLite.

    Returns a count of migrated rows per kind. Existing rows are upserted.
    """
    db.init_db()
    counts = {"notes": 0, "tasks": 0, "memory": 0}

    notes = _read_json("notes.json")
    if isinstance(notes, list):
        for n in notes:
            if not isinstance(n, dict) or not n.get("content"):
                continue
            db.add_note_db(
                n.get("id") or f"note_{n.get('created_at', '')}",
                n["content"],
                n.get("tags") or [],
                n.get("created_at") or db.now(),
            )
            counts["notes"] += 1

    tasks = _read_json("tasks.json")
    if isinstance(tasks, list):
        for t in tasks:
            if not isinstance(t, dict) or not t.get("title"):
                continue
            db.add_task_db(
                t.get("id") or t.get("title"),
                t["title"],
                t.get("description", ""),
                t.get("status", "pending"),
                t.get("priority", "medium"),
                t.get("created_at") or db.now(),
                t.get("updated_at") or db.now(),
            )
            counts["tasks"] += 1

    memory = _read_json("memory.json")
    if isinstance(memory, dict):
        for key, entry in memory.items():
            value = entry.get("value") if isinstance(entry, dict) else entry
            db.remember_db(key, value)
            counts["memory"] += 1

    if remove_json:
        for name in ("notes.json", "tasks.json", "memory.json"):
            path = os.path.join(get_data_dir(), name)
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    return counts
