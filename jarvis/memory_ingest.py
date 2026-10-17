"""Memory ingestion and import (Phase 21).

Turns free text / files into durable, de-duplicated memory *items* with a
source, tags and provenance, then offers ranked search over them.

Two extraction modes:

* ``heuristic`` (default, offline, deterministic) - line-level rules pick out
  key/value facts, preferences and notes.
* ``llm`` - asks the configured provider to pull facts out as JSON and falls
  back to the heuristic pass whenever the model is unavailable or answers
  with something unparseable.

Items live in the ``memory_items`` table (see :mod:`jarvis.db`) and never
overwrite the legacy key/value ``memory`` table, which is still served by the
old ``memory.remember`` / ``memory.recall`` tools.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import db

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MIN_LEN = 4
MAX_LEN = 600
MAX_NOTE_WORDS = 40
FACT_LIMIT = 40  # max items returned by search when no limit given
AUTO_INGEST_SETTING = "memory.auto_ingest"

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
BULLET_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+|>\s*)")
HASHTAG_RE = re.compile(r"(?:^|\s)#([A-Za-z0-9_\-]{2,30})")
CODE_RE = re.compile(
    r"^\s*(?:import\s|from\s+\w+\s+import|def\s|class\s|#include|#!\s*/|<\w+|[\}\]{\)]|"
    r"[\w.]+\s*=\s*[\w.]+\()"
)
SELF_RE = re.compile(
    r"^(?:my|our)\s+([A-Za-z0-9][A-Za-z0-9 _.\-']{0,40}?)\s+"
    r"(?:is|are|was|were|:)\s*(.+)$",
    re.I,
)
IS_RE = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9 _.\-']{0,60}?)\s+(?:is|are|was|were)\s+(.+)$",
    re.I,
)
KV_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9 _.\-']{0,60}?)\s*[:=]\s+(.+)$")
PREF_RE = re.compile(
    r"^(?:i|we)\s+(prefer|like|love|enjoy|use|live in|live at|work at|work for|"
    r"work on|work with|am|have|own|want|need|hate|dislike|speak|study|studied|"
    r"grew up in|was born in)\b\s*(.+)$",
    re.I,
)


class MemoryError(Exception):
    """Raised for user-facing ingestion/import problems."""


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------
def normalize(text: str) -> str:
    """Lowercase, unicode-fold and collapse whitespace for dedupe/search."""
    t = unicodedata.normalize("NFKC", text or "").lower()
    t = re.sub(r"\s+", " ", t).strip()
    return t.strip(" .!?,;:")


def make_hash(text: str) -> str:
    return hashlib.sha1(normalize(text).encode("utf-8")).hexdigest()


def slugify(text: str, words: int = 5) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", (text or "").lower())
    return "-".join(parts[:words]) or "note"


def _clean_tags(tags: Any) -> List[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        tags = re.split(r"[,\s]+", tags)
    out = []
    for t in tags:
        s = slugify(str(t), 3)
        if s and s not in out:
            out.append(s)
    return out


def new_item(
    text: str,
    key: str = "",
    kind: str = "fact",
    source: str = "",
    tags: Any = None,
    session: str = "",
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a memory-item dict, filling in the content hash and id."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    digest = make_hash(text)
    return {
        "item_id": "m" + digest[:16],
        "text": text,
        "key": slugify(key, 6) if key else "",
        "kind": kind or "fact",
        "source": (source or "").strip(),
        "tags": _clean_tags(tags),
        "session": session or "",
        "hash": digest,
        "created_at": created_at or db.now(),
    }


# ---------------------------------------------------------------------------
# Heuristic extraction
# ---------------------------------------------------------------------------
def extract_facts(
    text: str, source: str = "", tags: Any = None, session: str = ""
) -> List[Dict[str, Any]]:
    """Split free text into memory items using line-level rules."""
    base_tags = _clean_tags(tags)
    heading_tags: List[str] = []
    in_code = False
    items: List[Dict[str, Any]] = []

    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue

        heading = HEADING_RE.match(line.strip())
        if heading:
            heading_tags = _clean_tags([heading.group(2)])[:2]
            continue

        was_bullet = bool(BULLET_RE.match(line))
        line = BULLET_RE.sub("", line).strip()
        if not line:
            continue

        inline_tags = [m.group(1) for m in HASHTAG_RE.finditer(line)]
        line = HASHTAG_RE.sub("", line).strip()

        if len(line) < MIN_LEN or len(line) > MAX_LEN:
            continue
        if CODE_RE.match(line):
            continue

        item_tags = list(dict.fromkeys(base_tags + heading_tags + _clean_tags(inline_tags)))
        key, value, kind = _classify(line, was_bullet)

        # "My name is X and I live in Y." -> two clean facts instead of one blob
        clauses = _split_clauses(line)
        if clauses:
            classified = [_classify(c, False) for c in clauses]
            if all(c[0] and c[2] == "fact" for c in classified):
                for ck, cv, _ckind in classified:
                    items.append(
                        new_item(
                            f"{ck}: {cv}",
                            key=ck,
                            kind="fact",
                            source=source,
                            tags=item_tags,
                            session=session,
                        )
                    )
                continue

        if key is None:
            continue

        if kind == "fact" and value:
            stored = f"{key}: {value}"
        else:
            stored = line
        items.append(
            new_item(
                stored,
                key=key or "",
                kind=kind,
                source=source,
                tags=item_tags,
                session=session,
            )
        )
    return items


def _classify(line: str, was_bullet: bool):
    """Return (key, value, kind) for a cleaned line, or (None, None, None)."""
    m = SELF_RE.match(line)
    if m and _plausible_key(m.group(1)):
        return m.group(1).strip(), m.group(2).strip(), "fact"

    m = PREF_RE.match(line)
    if m:
        return f"i {m.group(1).lower()}".strip(), m.group(2).strip(), "fact"

    m = KV_RE.match(line)
    if m and _plausible_key(m.group(1)) and len(m.group(2)) >= 1:
        return m.group(1).strip(), m.group(2).strip(), "fact"

    m = IS_RE.match(line)
    if m and _plausible_key(m.group(1)) and len(m.group(2)) >= 2:
        return m.group(1).strip(), m.group(2).strip(), "fact"

    words = line.split()
    sentence_like = line.endswith((".", "!", "?")) or was_bullet
    if sentence_like and 1 <= len(words) <= MAX_NOTE_WORDS:
        return slugify(line), "", "note"
    return None, None, None


def _split_clauses(line: str) -> Optional[List[str]]:
    """Split ``... and ...`` / ``...; ...`` into clauses when that is safe.

    Returns the clauses only when the line is short enough to be a list of
    statements; the caller still has to verify every clause classifies as a
    clean fact, so conjunctions joining nouns (``milk and eggs``) fall back to
    normal whole-line handling.
    """
    if not 4 <= len(line) < 200:
        return None
    if " and " not in line.lower() and ";" not in line:
        return None
    parts = [p.strip() for p in re.split(r"\s+and\s+|;\s*", line, flags=re.I) if p.strip()]
    if not 2 <= len(parts) <= 4:
        return None
    return parts


def _plausible_key(key: str) -> bool:
    key = key.strip()
    if not 2 <= len(key) <= 60:
        return False
    if key.lower() in {"it", "this", "that", "there", "here", "they", "these", "those"}:
        return False
    return len(key.split()) <= 6


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
def store_items(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Persist items, de-duplicating by content hash. Returns counts."""
    added, skipped = 0, 0
    for it in items:
        if not it.get("text"):
            skipped += 1
            continue
        if not it.get("hash"):
            it = new_item(
                it["text"],
                key=it.get("key", ""),
                kind=it.get("kind", "fact"),
                source=it.get("source", ""),
                tags=it.get("tags"),
                session=it.get("session", ""),
            )
        if db.add_memory_item_db(it):
            added += 1
        else:
            skipped += 1
    return {"added": added, "skipped": skipped}


def ingest_text(
    text: str, source: str = "", tags: Any = None, session: str = ""
) -> Dict[str, Any]:
    """Ingest free text using the offline heuristic extractor."""
    items = extract_facts(text, source=source, tags=tags, session=session)
    counts = store_items(items)
    return {"mode": "heuristic", **counts}


async def aingest_text(
    text: str,
    source: str = "",
    tags: Any = None,
    mode: str = "heuristic",
    session: str = "",
) -> Dict[str, Any]:
    """Ingest free text, optionally asking the LLM to extract facts first."""
    used = "heuristic"
    items: List[Dict[str, Any]] = []
    if mode == "llm":
        items = await extract_with_llm(text, source=source, tags=tags, session=session)
        if items:
            used = "llm"
        else:
            items = extract_facts(text, source=source, tags=tags, session=session)
    else:
        items = extract_facts(text, source=source, tags=tags, session=session)
    counts = store_items(items)
    return {"mode": used, **counts}


LLM_INSTRUCTIONS = (
    "Extract durable personal facts and preferences from the user's text. "
    "Reply with ONLY a JSON array (no prose, no code fences). Each element is "
    'an object: {"key": short_label, "value": the_fact, "tags": [..]}. '
    "Skip filler, questions and anything temporary. Use [] if nothing."
)


async def extract_with_llm(
    text: str, source: str = "", tags: Any = None, session: str = ""
) -> List[Dict[str, Any]]:
    """Ask the configured provider for facts as JSON. Returns [] on any error."""
    from . import llm

    try:
        raw, _provider = await llm.complete(
            [
                {"role": "system", "content": LLM_INSTRUCTIONS},
                {"role": "user", "content": text[:6000]},
            ],
            temperature=0.1,
            max_tokens=1200,
        )
    except Exception:
        return []
    if not raw:
        return []
    parsed = _parse_json_array(raw)
    if parsed is None:
        return []
    items = []
    for row in parsed:
        if not isinstance(row, dict):
            continue
        value = str(row.get("value") or row.get("text") or "").strip()
        if not value:
            continue
        key = str(row.get("key") or "").strip()
        items.append(
            new_item(
                f"{key}: {value}" if key else value,
                key=key,
                kind="fact",
                source=source,
                tags=_clean_tags(tags) + _clean_tags(row.get("tags")),
                session=session,
            )
        )
    return items


def _parse_json_array(raw: str) -> Optional[List[Any]]:
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except Exception:
        return None
    return data if isinstance(data, list) else None


# ---------------------------------------------------------------------------
# Search & retrieval
# ---------------------------------------------------------------------------
def search(
    query: str = "",
    tags: Any = None,
    source: Optional[str] = None,
    limit: int = FACT_LIMIT,
    session: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Rank memory items against a query.

    Score = 3·key-hit + 2·tag-hit + 1·text-hit per query token, plus a small
    recency bonus so equally-relevant items surface newest-first.
    """
    items = db.list_memory_items_db(source=source, limit=1000)
    q_tokens = [t for t in re.findall(r"[a-z0-9]+", normalize(query)) if len(t) > 1]
    want_tags = set(_clean_tags(tags))
    filtered = []
    for idx, it in enumerate(items):
        if session and it.get("session") not in ("", session):
            continue
        if want_tags and not want_tags.issubset(set(it.get("tags", []))):
            continue
        filtered.append((idx, it))

    if not q_tokens:
        return [it for _idx, it in filtered[:limit]]

    scored = []
    for idx, it in filtered:
        key = normalize(it.get("key", ""))
        text = normalize(it.get("text", ""))
        itags = set(it.get("tags", []))
        score = 0
        for tok in q_tokens:
            if tok in key:
                score += 3
            if tok in itags:
                score += 2
            if tok in text:
                score += 1
        if score > 0:
            score += max(0, (1000 - idx) / 1000.0)  # recency tiebreak
            scored.append((score, it))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [it for _s, it in scored[:limit]]


def stats() -> Dict[str, Any]:
    facets = db.memory_item_facets_db()
    total = sum(s["count"] for s in facets["sources"])
    return {"total": total, **facets, "auto_ingest": is_auto_ingest_enabled()}


def delete_item(item_id: str) -> bool:
    return db.delete_memory_item_db(item_id)


def delete_source(source: str) -> int:
    return db.delete_memory_items_by_source_db(source)


def clear_all() -> int:
    return db.clear_memory_items_db()


# ---------------------------------------------------------------------------
# Import / export
# ---------------------------------------------------------------------------
def export_items() -> List[Dict[str, Any]]:
    """Return every memory item as plain JSON-serialisable dicts."""
    out = []
    for it in db.list_memory_items_db(limit=100000):
        out.append(
            {
                "text": it["text"],
                "key": it["key"],
                "kind": it["kind"],
                "source": it["source"],
                "tags": it["tags"],
                "created_at": it["created_at"],
            }
        )
    return out


def import_items(
    items: List[Dict[str, Any]], source_override: Optional[str] = None
) -> Dict[str, Any]:
    """Import a list of item dicts. Missing hashes/ids are regenerated."""
    prepared = []
    for row in items or []:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or row.get("value") or "").strip()
        if not text:
            continue
        prepared.append(
            new_item(
                text,
                key=row.get("key", ""),
                kind=row.get("kind", "fact"),
                source=source_override or row.get("source", ""),
                tags=row.get("tags"),
                session=row.get("session", ""),
                created_at=row.get("created_at"),
            )
        )
    counts = store_items(prepared)
    return {"mode": "import", **counts, "total": len(prepared)}


def import_file(path: str, source: Optional[str] = None) -> Dict[str, Any]:
    """Import a ``.json``/``.csv``/``.md``/``.txt`` file into memory.

    Paths outside the project/allowed bases are rejected (see
    :func:`jarvis.security.is_path_safe`).
    """
    from .security import is_path_safe

    if not is_path_safe(path):
        raise MemoryError(f"path not allowed: {path}")
    p = Path(path).expanduser()
    if not p.exists() or not p.is_file():
        raise MemoryError(f"file not found: {path}")

    suffix = p.suffix.lower()
    src = source or p.name
    raw = p.read_text(encoding="utf-8", errors="replace")

    if suffix == ".json":
        try:
            data = json.loads(raw)
        except Exception as exc:
            raise MemoryError(f"invalid JSON: {exc}") from exc
        if isinstance(data, dict):
            if isinstance(data.get("items"), list):
                data = data["items"]
            elif isinstance(data.get("memory"), dict):
                data = [
                    {"key": k, "text": f"{k}: {v}"}
                    for k, v in data["memory"].items()
                ]
            else:
                data = [{"key": k, "text": f"{k}: {v}"} for k, v in data.items()]
        if not isinstance(data, list):
            raise MemoryError("JSON must be a list or an object of items")
        return import_items(data, source_override=src)

    if suffix == ".csv":
        reader = csv.DictReader(io.StringIO(raw))
        rows = []
        for row in reader:
            text = (row.get("text") or row.get("value") or "").strip()
            key = (row.get("key") or "").strip()
            if not text:
                continue
            rows.append(
                {
                    "text": f"{key}: {text}" if key else text,
                    "key": key,
                    "tags": row.get("tags", ""),
                    "kind": row.get("kind", "fact"),
                    "source": row.get("source", ""),
                }
            )
        return import_items(rows, source_override=src)

    result = ingest_text(raw, source=src)
    return {**result, "mode": "file"}


def import_legacy_memory() -> Dict[str, Any]:
    """Turn rows of the old key/value ``memory`` table into memory items."""
    legacy = db.get_all_memory_db()
    rows = []
    for key, entry in legacy.items():
        value = entry.get("value") if isinstance(entry, dict) else entry
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        rows.append(
            {"text": f"{key}: {value}", "key": key, "source": "legacy", "kind": "fact"}
        )
    return import_items(rows)


# ---------------------------------------------------------------------------
# Auto-ingest setting
# ---------------------------------------------------------------------------
def is_auto_ingest_enabled() -> bool:
    return (db.get_setting(AUTO_INGEST_SETTING, "0") or "0") in ("1", "true", "on", "yes")


def set_auto_ingest(enabled: bool) -> None:
    db.set_setting(AUTO_INGEST_SETTING, "1" if enabled else "0")


def auto_ingest_turn(text: str, session: str = "") -> Dict[str, Any]:
    """Opportunistically capture facts from a chat turn (setting-gated)."""
    if not is_auto_ingest_enabled() or not (text or "").strip():
        return {"added": 0, "skipped": 0, "enabled": False}
    result = ingest_text(text, source="chat", session=session)
    return {**result, "enabled": True}
