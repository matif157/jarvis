"""Core Jarvis functionality - notes backed by SQLite."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List

from . import db


@dataclass
class Note:
    id: str
    content: str
    created_at: datetime = field(default_factory=datetime.now)
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "created_at": self.created_at.isoformat(),
            "tags": self.tags,
        }


class JarvisCore:
    """Core Jarvis engine for notes."""

    def __init__(self, data_dir: str = None):
        # Signature kept for backwards compatibility; storage is SQLite now.
        db.init_db()

    def add_note(self, content: str, tags: List[str] = None) -> Note:
        tags = tags or []
        note_id = f"note_{datetime.now().timestamp()}"
        note = Note(id=note_id, content=content, tags=tags)
        db.add_note_db(note_id, content, tags, note.created_at.strftime("%Y-%m-%dT%H:%M:%S"))
        return note

    def list_notes(self) -> List[Dict[str, Any]]:
        return db.get_notes_db()
