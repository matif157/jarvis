"""Enhanced memory with summaries and facts."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from . import db


class EnhancedMemory:
    def __init__(self):
        self.db = db

    def remember_fact(self, key: str, value: str, session: str = "global") -> None:
        self.db.remember_db(f"{session}:{key}", value)

    def get_facts(self, session: str = "global", limit: int = 20) -> List[dict]:
        allm = self.db.get_all_memory_db()
        results = []
        for k, v in allm.items():
            if k.startswith(f"{session}:"):
                results.append({"key": k.replace(f"{session}:", ""), "value": str(v)})
        return results[:limit]

    def summarize_conversation(self, history: List[dict]) -> Optional[str]:
        if len(history) < 6:
            return None
        # naive summary: take last few exchanges
        texts = []
        for h in history[-6:]:
            texts.append(h.get("content", "")[:80])
        return f"Recent: {' | '.join(texts)}"

    def search(self, query: str, session: str = "global", limit: int = 10) -> List[dict]:
        allm = self.db.get_all_memory_db()
        results = []
        for k, v in allm.items():
            if k.startswith(f"{session}:"):
                key = k.replace(f"{session}:", "")
                # try to extract value
                sval = v
                if isinstance(sval, dict):
                    sval = sval.get("value") or sval.get("data") or str(sval)
                sval = str(sval)
                # try to parse if looks like {"value": ...}
                try:
                    import json
                    if sval.strip().startswith("{") and sval.strip().endswith("}"):
                        sv = json.loads(sval)
                        if isinstance(sv, dict) and "value" in sv:
                            sval = sv["value"]
                except Exception:
                    pass
                results.append({"key": key, "value": str(sval)})
        q = (query or "").lower()
        if q:
            results = [
                r
                for r in results
                if q in r.get("key", "").lower() or q in str(r.get("value", "")).lower()
            ]
        return results[:limit]