"""Simple memory system for Jarvis"""

import json
import os
from datetime import datetime
from typing import Dict, List, Any


class Memory:
    """Local memory storage"""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.memory_file = os.path.join(data_dir, "memory.json")

    def remember(self, key: str, value: Any):
        memory = self._load()
        memory[key] = {
            "value": value,
            "updated_at": datetime.now().isoformat(),
        }
        self._save(memory)
        return True

    def recall(self, key: str) -> Any:
        memory = self._load()
        if key in memory:
            return memory[key]["value"]
        return None

    def forget(self, key: str):
        memory = self._load()
        if key in memory:
            del memory[key]
            self._save(memory)
        return True

    def _load(self) -> Dict[str, Any]:
        if not os.path.exists(self.memory_file):
            return {}
        try:
            with open(self.memory_file, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self, memory: Dict[str, Any]):
        with open(self.memory_file, "w") as f:
            json.dump(memory, f, indent=2)
