"""Simple memory system for Jarvis - SQLite backed."""

from typing import Any, Dict

from . import db


class Memory:
    """Local memory storage backed by SQLite."""

    def __init__(self, data_dir: str = None):
        # Signature kept for backwards compatibility; storage is SQLite now.
        db.init_db()

    def remember(self, key: str, value: Any) -> bool:
        db.remember_db(key, value)
        return True

    def recall(self, key: str) -> Any:
        return db.recall_db(key)

    def forget(self, key: str) -> bool:
        db.forget_db(key)
        return True

    def all(self) -> Dict[str, Any]:
        return db.get_all_memory_db()
