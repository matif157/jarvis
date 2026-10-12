"""Database layer for Jarvis - SQLite persistence"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config

DB_PATH = Path(config.get_data_dir()) / "jarvis.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def now() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect() -> sqlite3.Connection:
    """Connect to database with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize database schema."""
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


SCHEMA = """
-- Settings for config and API keys
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Notes (migrated from JSON)
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id TEXT UNIQUE NOT NULL,
    content TEXT NOT NULL,
    tags TEXT DEFAULT '[]',
    created_at TEXT NOT NULL
);

-- Tasks (migrated from JSON)
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    priority TEXT DEFAULT 'medium',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Memory key-value store (migrated from JSON)
CREATE TABLE IF NOT EXISTS memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Conversation messages
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    labels TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);
"""


def set_setting(key: str, value: str) -> None:
    """Set a setting in database."""
    conn = connect()
    conn.execute(
        "INSERT OR REPLACE INTO settings(key, value, updated_at) VALUES (?,?,?)",
        (key, value, now()),
    )
    conn.commit()
    conn.close()


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get a setting from database."""
    conn = connect()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    if not row:
        return default
    return row["value"]


def delete_setting(key: str) -> None:
    """Delete a setting from database."""
    conn = connect()
    conn.execute("DELETE FROM settings WHERE key=?", (key,))
    conn.commit()
    conn.close()


# Notes
def add_note_db(note_id: str, content: str, tags: List[str] = None, created_at: str = None) -> None:
    if tags is None:
        tags = []
    if created_at is None:
        created_at = now()
    conn = connect()
    conn.execute(
        "INSERT OR REPLACE INTO notes(note_id, content, tags, created_at) VALUES (?,?,?,?)",
        (note_id, content, json.dumps(tags), created_at),
    )
    conn.commit()
    conn.close()


def get_notes_db() -> List[Dict[str, Any]]:
    conn = connect()
    rows = conn.execute("SELECT * FROM notes ORDER BY created_at DESC").fetchall()
    conn.close()
    result = []
    for r in rows:
        result.append({
            "id": r["note_id"],
            "content": r["content"],
            "tags": json.loads(r["tags"] or "[]"),
            "created_at": r["created_at"],
        })
    return result


# Tasks
def add_task_db(task_id: str, title: str, description: str = "", status: str = "pending",
                priority: str = "medium", created_at: str = None, updated_at: str = None) -> None:
    if created_at is None:
        created_at = now()
    if updated_at is None:
        updated_at = now()
    conn = connect()
    conn.execute(
        "INSERT OR REPLACE INTO tasks(task_id, title, description, status, priority, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (task_id, title, description, status, priority, created_at, updated_at),
    )
    conn.commit()
    conn.close()


def get_tasks_db() -> List[Dict[str, Any]]:
    conn = connect()
    rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
    conn.close()
    result = []
    for r in rows:
        result.append({
            "id": r["task_id"],
            "title": r["title"],
            "description": r["description"],
            "status": r["status"],
            "priority": r["priority"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        })
    return result


def complete_task_db(task_id: str) -> bool:
    conn = connect()
    cur = conn.execute(
        "UPDATE tasks SET status='completed', updated_at=? WHERE task_id=?",
        (now(), task_id),
    )
    conn.commit()
    rows = cur.rowcount
    conn.close()
    return rows > 0


# Memory
def remember_db(key: str, value: Any) -> None:
    conn = connect()
    conn.execute(
        "INSERT OR REPLACE INTO memory(key, value, updated_at) VALUES (?,?,?)",
        (key, json.dumps(value) if not isinstance(value, str) else value, now()),
    )
    conn.commit()
    conn.close()


def recall_db(key: str) -> Optional[Any]:
    conn = connect()
    row = conn.execute("SELECT value FROM memory WHERE key=?", (key,)).fetchone()
    conn.close()
    if not row:
        return None
    try:
        # Try to parse as JSON
        return json.loads(row["value"])
    except Exception:
        return row["value"]


def forget_db(key: str) -> None:
    conn = connect()
    conn.execute("DELETE FROM memory WHERE key=?", (key,))
    conn.commit()
    conn.close()


def get_all_memory_db() -> Dict[str, Any]:
    conn = connect()
    rows = conn.execute("SELECT key, value, updated_at FROM memory").fetchall()
    conn.close()
    result = {}
    for r in rows:
        try:
            result[r["key"]] = {
                "value": json.loads(r["value"]) if r["value"].startswith(("[", "{")) else r["value"],
                "updated_at": r["updated_at"],
            }
        except Exception:
            result[r["key"]] = {"value": r["value"], "updated_at": r["updated_at"]}
    return result


# Messages
def save_message(session_id: str, role: str, content: str, labels: Dict = None) -> None:
    if labels is None:
        labels = {}
    conn = connect()
    conn.execute(
        "INSERT INTO messages(session_id, role, content, labels, created_at) VALUES (?,?,?,?,?)",
        (session_id, role, content, json.dumps(labels), now()),
    )
    conn.commit()
    conn.close()


# Initialize DB on import
try:
    init_db()
except Exception:
    pass
