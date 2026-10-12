"""Core Jarvis functionality"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any
import json
import os


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
    """Core Jarvis engine"""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.notes_file = os.path.join(data_dir, "notes.json")

    def add_note(self, content: str, tags: List[str] = None) -> Note:
        tags = tags or []
        note_id = f"note_{datetime.now().timestamp()}"
        note = Note(id=note_id, content=content, tags=tags)
        self._save_note(note)
        return note

    def _save_note(self, note: Note):
        notes = self._load_notes()
        notes.append(note.to_dict())
        with open(self.notes_file, "w") as f:
            json.dump(notes, f, indent=2)

    def _load_notes(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.notes_file):
            return []
        with open(self.notes_file, "r") as f:
            return json.load(f)
