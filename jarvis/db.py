"""Database layer for Jarvis - SQLite persistence"""

from __future__ import annotations

import json
import sqlite3
import uuid
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
    _migrate_sync()


def _migrate_sync() -> None:
    """Give every message a stable global id so chats can sync across devices."""
    try:
        conn = connect()
        cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
        if "msg_id" not in cols:
            conn.execute("ALTER TABLE messages ADD COLUMN msg_id TEXT")
        rows = conn.execute("SELECT id FROM messages WHERE msg_id IS NULL").fetchall()
        for r in rows:
            conn.execute(
                "UPDATE messages SET msg_id=? WHERE id=?", (uuid.uuid4().hex, r["id"])
            )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_msg_id ON messages(msg_id)"
        )
        conn.commit()
        conn.close()
    except Exception:  # noqa: BLE001 - sync ids are best-effort, never fatal
        pass


def _journal(entity: str, entity_id: str, op: str, payload: Optional[Dict[str, Any]] = None) -> None:
    """Append a change to the sync journal (never fatal, never recursive).

    Imported lazily: :mod:`jarvis.sync` imports this module, so a top-level
    import here would be circular. Keys under ``secret.`` and ``sync.`` are the
    device's own and are deliberately not journalled.
    """
    if entity == "settings" and entity_id.startswith(("secret.", "sync.")):
        return
    try:
        from . import sync

        sync.record(entity, entity_id, op, payload)
    except Exception:  # noqa: BLE001 - journalling must not break a write
        pass


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

-- Ingested memory items (Phase 21): facts/notes with source, tags and dedupe
CREATE TABLE IF NOT EXISTS memory_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT UNIQUE NOT NULL,
    text TEXT NOT NULL,
    key TEXT DEFAULT '',
    kind TEXT DEFAULT 'fact',
    source TEXT DEFAULT '',
    tags TEXT DEFAULT '',
    session TEXT DEFAULT '',
    hash TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_items_source ON memory_items(source);
CREATE INDEX IF NOT EXISTS idx_memory_items_hash ON memory_items(hash);

-- WhatsApp messages (Phase 22): the mapped chat structure
CREATE TABLE IF NOT EXISTS wa_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat TEXT NOT NULL,
    sender TEXT DEFAULT '',
    direction TEXT NOT NULL DEFAULT 'in',
    text TEXT NOT NULL,
    ts TEXT DEFAULT '',
    source TEXT NOT NULL DEFAULT 'live',
    hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_wa_messages_chat ON wa_messages(chat);
CREATE UNIQUE INDEX IF NOT EXISTS idx_wa_messages_hash ON wa_messages(hash);

-- Device control audit (Phase 24): every action that reached the bridge
CREATE TABLE IF NOT EXISTS device_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    params TEXT DEFAULT '',
    ok INTEGER NOT NULL,
    error TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_device_audit_ts ON device_audit(ts);

-- Cross-surface sync (Phase 25): an append-only journal of every change to a
-- syncable table. Devices exchange journal entries; deletes travel as tombstones
-- (op='delete'), so removals propagate instead of resurrecting on the next pull.
CREATE TABLE IF NOT EXISTS sync_journal (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    entity TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    op TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    ts TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sync_journal_seq ON sync_journal(seq);
CREATE INDEX IF NOT EXISTS idx_sync_journal_entity ON sync_journal(entity, entity_id);

-- Last write seen for an entity, per the (ts, device_id) order used to resolve
-- conflicts deterministically across devices (last-write-wins with a tiebreak).
CREATE TABLE IF NOT EXISTS sync_seen (
    entity TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    device_id TEXT NOT NULL,
    PRIMARY KEY (entity, entity_id)
);
"""


def set_setting(key: str, value: str) -> None:
    """Set a setting in database."""
    conn = connect()
    ts = now()
    conn.execute(
        "INSERT OR REPLACE INTO settings(key, value, updated_at) VALUES (?,?,?)",
        (key, value, ts),
    )
    conn.commit()
    conn.close()
    _journal("settings", key, "upsert", {"key": key, "value": value, "updated_at": ts})


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
    _journal("settings", key, "delete", None)


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
    _journal(
        "notes",
        note_id,
        "upsert",
        {"note_id": note_id, "content": content, "tags": json.dumps(tags), "created_at": created_at},
    )


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
    _journal(
        "tasks",
        task_id,
        "upsert",
        {
            "task_id": task_id,
            "title": title,
            "description": description,
            "status": status,
            "priority": priority,
            "created_at": created_at,
            "updated_at": updated_at,
        },
    )


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
    ts = now()
    cur = conn.execute(
        "UPDATE tasks SET status='completed', updated_at=? WHERE task_id=?",
        (ts, task_id),
    )
    conn.commit()
    rows = cur.rowcount
    if rows > 0:
        row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row:
            _journal("tasks", task_id, "upsert", {k: row[k] for k in row.keys()})
    conn.close()
    return rows > 0


# Memory
def remember_db(key: str, value: Any) -> None:
    conn = connect()
    ts = now()
    stored = json.dumps(value) if not isinstance(value, str) else value
    conn.execute(
        "INSERT OR REPLACE INTO memory(key, value, updated_at) VALUES (?,?,?)",
        (key, stored, ts),
    )
    conn.commit()
    conn.close()
    _journal("memory", key, "upsert", {"key": key, "value": stored, "updated_at": ts})


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
    _journal("memory", key, "delete", None)


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


# Ingested memory items (Phase 21)
def _memory_item_row(r: sqlite3.Row) -> Dict[str, Any]:
    return {
        "item_id": r["item_id"],
        "text": r["text"],
        "key": r["key"] or "",
        "kind": r["kind"] or "fact",
        "source": r["source"] or "",
        "tags": [t for t in (r["tags"] or "").split(",") if t],
        "session": r["session"] or "",
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def add_memory_item_db(item: Dict[str, Any]) -> bool:
    """Insert one memory item, ignoring duplicates (same hash). True if added."""
    tags = item.get("tags") or []
    if isinstance(tags, str):
        tags = [t for t in tags.split(",") if t]
    ts = item.get("created_at") or now()
    conn = connect()
    cur = conn.execute(
        """INSERT OR IGNORE INTO memory_items
           (item_id, text, key, kind, source, tags, session, hash, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            item["item_id"],
            item["text"],
            item.get("key", ""),
            item.get("kind", "fact"),
            item.get("source", ""),
            ",".join(tags),
            item.get("session", ""),
            item["hash"],
            ts,
            ts,
        ),
    )
    conn.commit()
    added = cur.rowcount > 0
    conn.close()
    if added:
        _journal(
            "memory_items",
            item["item_id"],
            "upsert",
            {
                "item_id": item["item_id"],
                "text": item["text"],
                "key": item.get("key", ""),
                "kind": item.get("kind", "fact"),
                "source": item.get("source", ""),
                "tags": ",".join(tags),
                "session": item.get("session", ""),
                "hash": item["hash"],
                "created_at": ts,
                "updated_at": ts,
            },
        )
    return added


def list_memory_items_db(source: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
    conn = connect()
    if source:
        rows = conn.execute(
            "SELECT * FROM memory_items WHERE source=? ORDER BY created_at DESC, id DESC LIMIT ?",
            (source, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM memory_items ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    return [_memory_item_row(r) for r in rows]


def get_memory_item_db(item_id: str) -> Optional[Dict[str, Any]]:
    conn = connect()
    row = conn.execute("SELECT * FROM memory_items WHERE item_id=?", (item_id,)).fetchone()
    conn.close()
    return _memory_item_row(row) if row else None


def delete_memory_item_db(item_id: str) -> bool:
    conn = connect()
    cur = conn.execute("DELETE FROM memory_items WHERE item_id=?", (item_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    if deleted:
        _journal("memory_items", item_id, "delete", None)
    return deleted


def delete_memory_items_by_source_db(source: str) -> int:
    conn = connect()
    ids = [
        r["item_id"]
        for r in conn.execute(
            "SELECT item_id FROM memory_items WHERE source=?", (source,)
        ).fetchall()
    ]
    cur = conn.execute("DELETE FROM memory_items WHERE source=?", (source,))
    conn.commit()
    count = cur.rowcount
    conn.close()
    for item_id in ids:
        _journal("memory_items", item_id, "delete", None)
    return count


def clear_memory_items_db() -> int:
    conn = connect()
    ids = [r["item_id"] for r in conn.execute("SELECT item_id FROM memory_items").fetchall()]
    cur = conn.execute("DELETE FROM memory_items")
    conn.commit()
    count = cur.rowcount
    conn.close()
    for item_id in ids:
        _journal("memory_items", item_id, "delete", None)
    return count


def memory_item_facets_db() -> Dict[str, List[Dict[str, Any]]]:
    """Distinct sources, tags and kinds with counts."""
    conn = connect()
    rows = conn.execute("SELECT source, tags, kind FROM memory_items").fetchall()
    conn.close()
    sources: Dict[str, int] = {}
    tags: Dict[str, int] = {}
    kinds: Dict[str, int] = {}
    for r in rows:
        s = r["source"] or "(none)"
        sources[s] = sources.get(s, 0) + 1
        k = r["kind"] or "fact"
        kinds[k] = kinds.get(k, 0) + 1
        for t in (r["tags"] or "").split(","):
            if t:
                tags[t] = tags.get(t, 0) + 1
    return {
        "sources": sorted(
            ({"source": k, "count": v} for k, v in sources.items()),
            key=lambda x: (-x["count"], x["source"]),
        ),
        "tags": sorted(
            ({"tag": k, "count": v} for k, v in tags.items()),
            key=lambda x: (-x["count"], x["tag"]),
        ),
        "kinds": sorted(
            ({"kind": k, "count": v} for k, v in kinds.items()),
            key=lambda x: (-x["count"], x["kind"]),
        ),
    }


# WhatsApp messages (Phase 22)
def _wa_row(r: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": r["id"],
        "chat": r["chat"],
        "sender": r["sender"] or "",
        "direction": r["direction"],
        "text": r["text"],
        "ts": r["ts"] or "",
        "source": r["source"],
    }


def add_wa_message_db(message: Dict[str, Any]) -> bool:
    """Insert one WhatsApp message. Returns False when the hash already exists."""
    conn = connect()
    cur = conn.execute(
        """INSERT OR IGNORE INTO wa_messages
           (chat, sender, direction, text, ts, source, hash, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            message["chat"],
            message.get("sender", ""),
            message.get("direction", "in"),
            message["text"],
            message.get("ts", ""),
            message.get("source", "live"),
            message["hash"],
            message.get("created_at") or now(),
        ),
    )
    conn.commit()
    inserted = cur.rowcount > 0
    conn.close()
    if inserted:
        _journal(
            "wa_messages",
            message["hash"],
            "upsert",
            {
                "chat": message["chat"],
                "sender": message.get("sender", ""),
                "direction": message.get("direction", "in"),
                "text": message["text"],
                "ts": message.get("ts", ""),
                "source": message.get("source", "live"),
                "hash": message["hash"],
                "created_at": message.get("created_at") or now(),
            },
        )
    return inserted


def list_wa_messages_db(chat: str, limit: int = 100) -> List[Dict[str, Any]]:
    conn = connect()
    rows = conn.execute(
        "SELECT * FROM wa_messages WHERE chat=? "
        "ORDER BY (ts=''), ts, id LIMIT ?",
        (chat, limit),
    ).fetchall()
    conn.close()
    return [_wa_row(r) for r in rows]


def list_wa_chats_db(limit: int = 500) -> List[Dict[str, Any]]:
    conn = connect()
    rows = conn.execute(
        """SELECT chat,
                  COUNT(*) AS total,
                  SUM(CASE WHEN direction='in' THEN 1 ELSE 0 END) AS inbound,
                  SUM(CASE WHEN direction='out' THEN 1 ELSE 0 END) AS outbound,
                  MAX(ts) AS last_ts
           FROM wa_messages GROUP BY chat
           ORDER BY last_ts DESC, chat
           LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [
        {
            "chat": r["chat"],
            "total": r["total"],
            "inbound": r["inbound"] or 0,
            "outbound": r["outbound"] or 0,
            "last_ts": r["last_ts"] or "",
        }
        for r in rows
    ]


def count_wa_messages_db() -> int:
    conn = connect()
    row = conn.execute("SELECT COUNT(*) AS n FROM wa_messages").fetchone()
    conn.close()
    return int(row["n"]) if row else 0


def last_outbound_ts_db(chat: str) -> str:
    """Most recent sent-reply time (ISO) for cooldown checks; imports excluded."""
    conn = connect()
    row = conn.execute(
        "SELECT MAX(created_at) AS ts FROM wa_messages "
        "WHERE chat=? AND direction='out' AND source='live'",
        (chat,),
    ).fetchone()
    conn.close()
    return row["ts"] or "" if row else ""


def delete_wa_messages_db(chat: str) -> int:
    conn = connect()
    hashes = [
        r["hash"]
        for r in conn.execute("SELECT hash FROM wa_messages WHERE chat=?", (chat,)).fetchall()
    ]
    cur = conn.execute("DELETE FROM wa_messages WHERE chat=?", (chat,))
    conn.commit()
    count = cur.rowcount
    conn.close()
    for h in hashes:
        _journal("wa_messages", h, "delete", None)
    return count


# Device control audit (Phase 24)
DEVICE_AUDIT_MAX = 2000


def add_device_audit_db(action: str, params: str, ok: bool, error: str = "") -> None:
    """Append one executed device action; prunes to the newest DEVICE_AUDIT_MAX."""
    conn = connect()
    conn.execute(
        "INSERT INTO device_audit(ts, action, params, ok, error) VALUES (?,?,?,?,?)",
        (now(), action, params, 1 if ok else 0, error),
    )
    conn.execute(
        "DELETE FROM device_audit WHERE id NOT IN "
        "(SELECT id FROM device_audit ORDER BY id DESC LIMIT ?)",
        (DEVICE_AUDIT_MAX,),
    )
    conn.commit()
    conn.close()


def list_device_audit_db(limit: int = 100) -> List[Dict[str, Any]]:
    """Newest-first audit rows (ts, action, params, ok, error)."""
    conn = connect()
    rows = conn.execute(
        "SELECT ts, action, params, ok, error FROM device_audit ORDER BY id DESC LIMIT ?",
        (max(1, min(int(limit), DEVICE_AUDIT_MAX)),),
    ).fetchall()
    conn.close()
    return [
        {
            "ts": r["ts"],
            "action": r["action"],
            "params": r["params"],
            "ok": bool(r["ok"]),
            "error": r["error"],
        }
        for r in rows
    ]


def count_device_audit_db() -> int:
    conn = connect()
    row = conn.execute("SELECT COUNT(*) AS n FROM device_audit").fetchone()
    conn.close()
    return int(row["n"]) if row else 0


# Messages
def save_message(session_id: str, role: str, content: str, labels: Dict = None) -> str:
    """Persist one chat message and return its stable global id (``msg_id``)."""
    if labels is None:
        labels = {}
    msg_id = uuid.uuid4().hex
    ts = now()
    conn = connect()
    conn.execute(
        "INSERT INTO messages(session_id, role, content, labels, created_at, msg_id) VALUES (?,?,?,?,?,?)",
        (session_id, role, content, json.dumps(labels), ts, msg_id),
    )
    conn.commit()
    conn.close()
    _journal(
        "messages",
        msg_id,
        "upsert",
        {
            "msg_id": msg_id,
            "session_id": session_id,
            "role": role,
            "content": content,
            "labels": json.dumps(labels),
            "created_at": ts,
        },
    )
    return msg_id


def list_messages_db(session_id: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
    """Newest-last chat messages, optionally filtered to one session."""
    conn = connect()
    if session_id:
        rows = conn.execute(
            "SELECT msg_id, session_id, role, content, labels, created_at FROM messages "
            "WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (session_id, max(1, int(limit))),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT msg_id, session_id, role, content, labels, created_at FROM messages "
            "ORDER BY id DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
    conn.close()
    out = [
        {
            "msg_id": r["msg_id"],
            "session_id": r["session_id"],
            "role": r["role"],
            "content": r["content"],
            "labels": r["labels"] or "{}",
            "created_at": r["created_at"],
        }
        for r in rows
    ]
    out.reverse()
    return out


# Initialize DB on import
try:
    init_db()
except Exception:
    pass
