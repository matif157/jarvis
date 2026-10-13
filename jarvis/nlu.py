"""Simple natural language understanding helpers."""

from __future__ import annotations

import re
from typing import Dict, List, Optional


def classify_intent(text: str) -> Dict[str, str]:
    t = text.lower()
    if re.search(r"\b(time|what time)\b", t):
        return {"intent": "time", "confidence": "high"}
    if re.search(r"\b(date|today)\b", t):
        return {"intent": "date", "confidence": "high"}
    if re.search(r"\b(note|save note|remember this)\b", t):
        return {"intent": "note", "confidence": "high"}
    if re.search(r"\b(task|todo|add task)\b", t):
        return {"intent": "task", "confidence": "high"}
    if re.search(r"\b(weather)\b", t):
        return {"intent": "weather", "confidence": "high"}
    if re.search(r"\b(find|search|locate)\b", t):
        return {"intent": "find", "confidence": "medium"}
    if re.search(r"\b(hello|hi|hey)\b", t):
        return {"intent": "greet", "confidence": "high"}
    if re.search(r"\b(help)\b", t):
        return {"intent": "help", "confidence": "high"}
    return {"intent": "general", "confidence": "low"}
