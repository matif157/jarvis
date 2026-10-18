"""Cross-surface sync for Jarvis (Phase 25).

The APK, the WebUI and the desktop/CLI all read and write the same kinds of
rows (notes, tasks, memory, chat messages, ...). This module keeps those rows
identical across devices:

* every write appends a line to ``sync_journal`` (see :func:`jarvis.db._journal`);
* two devices trade journal lines over the LAN (``POST /api/sync/...``) and
  replay them locally;
* conflicts resolve last-write-wins on ``(ts, device_id)`` so every device
  converges on the same result regardless of the order it heard the news;
* deletes travel as tombstones so a row removed on the phone does not come back
  on the next pull from the laptop.

The transport is deliberately plain HTTP + JSON: the phone already serves the
WebUI on the LAN, and cleartext is allowed in the manifest, so a peer is just a
``base_url`` plus a shared token. Nothing here talks to a third party unless the
user opts into the optional GitHub snapshot mirror.
"""
from __future__ import annotations

import json
import os
import platform
import socket
import socketserver
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import httpx

from . import db

# Settings keys (all under the ``sync.`` namespace; db._journal never records
# these, so configuring sync can never trigger a sync loop).
K_ENABLED = "sync.enabled"
K_DEVICE_ID = "sync.device_id"
K_DEVICE_NAME = "sync.device_name"
K_TOKEN = "sync.token"
K_PEERS = "sync.peers"
K_CURSORS = "sync.cursors"
K_INTERVAL = "sync.interval"
K_LAST_SYNC = "sync.last_sync"
K_LAST_RESULT = "sync.last_result"
K_GITHUB_REPO = "sync.github.repo"
K_GITHUB_TOKEN = "sync.github.token"
K_GITHUB_PATH = "sync.github.path"
K_GITHUB_BRANCH = "sync.github.branch"
K_PORT = "sync.port"

# What the WebUI is allowed to read/write, and how a plain ``sync.`` key is typed.
CONFIG_KEYS = {
    K_ENABLED: ("enabled", "bool"),
    K_DEVICE_NAME: ("device_name", "str"),
    K_INTERVAL: ("interval", "int"),
    K_PORT: ("port", "int"),
    K_GITHUB_REPO: ("github_repo", "str"),
    K_GITHUB_PATH: ("github_path", "str"),
    K_GITHUB_BRANCH: ("github_branch", "str"),
}
# Secrets are accepted on write but never echoed back by the status endpoint.
SECRET_KEYS = {K_TOKEN: "token", K_GITHUB_TOKEN: "github_token"}

DEFAULT_INTERVAL = 30
MIN_INTERVAL = 5
DEFAULT_PORT = 8772
MAX_ENTRIES = 2000

# How to project an entity's journal payload onto its table. ``cols`` are pulled
# from the payload in order; anything missing becomes NULL/default.
ENTITIES: Dict[str, Dict[str, Any]] = {
    "settings": {"table": "settings", "pk": "key", "cols": ["key", "value", "updated_at"]},
    "memory": {"table": "memory", "pk": "key", "cols": ["key", "value", "updated_at"]},
    "notes": {"table": "notes", "pk": "note_id", "cols": ["note_id", "content", "tags", "created_at"]},
    "tasks": {
        "table": "tasks",
        "pk": "task_id",
        "cols": ["task_id", "title", "description", "status", "priority", "created_at", "updated_at"],
    },
    "memory_items": {
        "table": "memory_items",
        "pk": "item_id",
        "cols": [
            "item_id", "text", "key", "kind", "source", "tags", "session",
            "hash", "created_at", "updated_at",
        ],
    },
    "messages": {
        "table": "messages",
        "pk": "msg_id",
        "cols": ["msg_id", "session_id", "role", "content", "labels", "created_at"],
    },
    "wa_messages": {
        "table": "wa_messages",
        "pk": "hash",
        "cols": ["chat", "sender", "direction", "text", "ts", "source", "hash", "created_at"],
    },
}

_auto_lock = threading.Lock()
_auto_thread: Optional[threading.Thread] = None
_auto_stop = threading.Event()


# --------------------------------------------------------------------------- #
# Settings / identity
# --------------------------------------------------------------------------- #
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_config() -> Dict[str, Any]:
    """Return the non-secret sync configuration for display."""
    cfg: Dict[str, Any] = {
        "device_id": device_id(),
        "device_name": device_name(),
        "peers": get_peers(),
        "token_set": bool(db.get_setting(K_TOKEN)),
        "github_token_set": bool(db.get_setting(K_GITHUB_TOKEN)),
    }
    for key, (name, kind) in CONFIG_KEYS.items():
        raw = db.get_setting(key, "")
        cfg[name] = _coerce(raw, kind)
    if cfg.get("interval") is None:
        cfg["interval"] = DEFAULT_INTERVAL
    return cfg


def _coerce(raw: Any, kind: str) -> Any:
    if kind == "bool":
        return str(raw) in ("1", "true", "True", "yes", "on")
    if kind == "int":
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    return raw if raw is not None else ""


def set_config(values: Dict[str, Any]) -> Dict[str, Any]:
    """Apply a subset of sync settings from the WebUI/API."""
    for key, (name, kind) in CONFIG_KEYS.items():
        if name not in values:
            continue
        val = values[name]
        if kind == "bool":
            db.set_setting(key, "1" if val else "0")
        elif kind == "int":
            try:
                n = int(val)
            except (TypeError, ValueError):
                continue
            if name == "port":
                n = max(1024, min(65535, n))
            else:
                n = max(MIN_INTERVAL, n)
            db.set_setting(key, str(n))
        else:
            db.set_setting(key, str(val))
    for key, name in SECRET_KEYS.items():
        if name in values:
            db.set_setting(key, str(values[name]))
    if "peers" in values and isinstance(values["peers"], list):
        set_peers(values["peers"])
    return get_config()


def device_id() -> str:
    did = db.get_setting(K_DEVICE_ID)
    if not did:
        did = uuid.uuid4().hex
        db.set_setting(K_DEVICE_ID, did)
    return did


def device_name() -> str:
    name = db.get_setting(K_DEVICE_NAME)
    if not name:
        name = platform.node() or socket.gethostname() or "jarvis"
        db.set_setting(K_DEVICE_NAME, name)
    return name


def ensure_token() -> str:
    """Return the shared token, creating one on first use."""
    token = db.get_setting(K_TOKEN)
    if not token:
        token = uuid.uuid4().hex
        db.set_setting(K_TOKEN, token)
    return token


def enabled() -> bool:
    return str(db.get_setting(K_ENABLED, "0")) in ("1", "true", "True", "yes", "on")


def interval() -> int:
    try:
        return max(MIN_INTERVAL, int(db.get_setting(K_INTERVAL, str(DEFAULT_INTERVAL))))
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL


def configured_port() -> int:
    env = os.getenv("JARVIS_SYNC_PORT")
    if env:
        try:
            return int(env)
        except ValueError:
            pass
    try:
        return int(db.get_setting(K_PORT, str(DEFAULT_PORT)))
    except (TypeError, ValueError):
        return DEFAULT_PORT


def local_ips() -> List[str]:
    """Best-effort LAN addresses, so the UI can suggest a peer URL.

    Only the routing-table trick is used: ``getaddrinfo``/``gethostbyname`` on a
    phone-hostname can block for seconds on a DNS timeout.
    """
    ips = set()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
    except Exception:  # noqa: BLE001 - offline is fine, just no suggestion
        pass
    finally:
        s.close()
    ips.discard("127.0.0.1")
    return sorted(ips)


def get_peers() -> List[Dict[str, str]]:
    return _read_peers()


def set_peers(peers: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    clean: List[Dict[str, str]] = []
    for p in peers:
        url = str(p.get("url", "")).strip().rstrip("/")
        if not url:
            continue
        clean.append({"url": url, "token": str(p.get("token", ""))})
    db.set_setting(K_PEERS, json.dumps(clean))
    return clean


def get_peers() -> List[Dict[str, str]]:  # noqa: F811 - redefined below, kept obvious
    return _read_peers()


def _read_peers() -> List[Dict[str, str]]:
    raw = db.get_setting(K_PEERS)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    out: List[Dict[str, str]] = []
    for p in data if isinstance(data, list) else []:
        url = str(p.get("url", "")).strip().rstrip("/")
        if url:
            out.append({"url": url, "token": str(p.get("token", ""))})
    return out


def _cursors() -> Dict[str, Dict[str, int]]:
    raw = db.get_setting(K_CURSORS)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


def _set_cursors(cursors: Dict[str, Dict[str, int]]) -> None:
    db.set_setting(K_CURSORS, json.dumps(cursors))


# --------------------------------------------------------------------------- #
# Journal
# --------------------------------------------------------------------------- #
def record(entity: str, entity_id: str, op: str, payload: Optional[Dict[str, Any]]) -> None:
    """Append a local change to the journal. Called from :mod:`jarvis.db`."""
    if entity not in ENTITIES:
        return
    if op == "delete" or not payload:
        # A tombstone only needs to name the row it removes.
        payload = {ENTITIES[entity]["pk"]: entity_id}
    did = device_id()
    ts = _now()
    conn = db.connect()
    conn.execute(
        "INSERT INTO sync_journal(device_id, entity, entity_id, op, payload, ts) VALUES (?,?,?,?,?,?)",
        (did, entity, str(entity_id), op, json.dumps(payload or {}), ts),
    )
    # Remember this as the newest write so an older remote replay is skipped.
    conn.execute(
        "INSERT OR REPLACE INTO sync_seen(entity, entity_id, ts, device_id) VALUES (?,?,?,?)",
        (entity, str(entity_id), ts, did),
    )
    conn.commit()
    conn.close()


def journal_size() -> int:
    conn = db.connect()
    row = conn.execute("SELECT COUNT(*) AS n FROM sync_journal").fetchone()
    conn.close()
    return int(row["n"]) if row else 0


def changes_since(cursor: int, limit: int = MAX_ENTRIES) -> Tuple[List[Dict[str, Any]], int]:
    """Return journal lines with ``seq > cursor`` and the new high-water mark."""
    conn = db.connect()
    rows = conn.execute(
        "SELECT seq, device_id, entity, entity_id, op, payload, ts "
        "FROM sync_journal WHERE seq > ? ORDER BY seq ASC LIMIT ?",
        (int(cursor), int(limit)),
    ).fetchall()
    conn.close()
    entries = [
        {
            "seq": int(r["seq"]),
            "device_id": r["device_id"],
            "entity": r["entity"],
            "entity_id": r["entity_id"],
            "op": r["op"],
            "payload": json.loads(r["payload"] or "{}"),
            "ts": r["ts"],
        }
        for r in rows
    ]
    new_cursor = entries[-1]["seq"] if entries else int(cursor)
    return entries, new_cursor


def _seen() -> Dict[Tuple[str, str], Tuple[str, str]]:
    conn = db.connect()
    rows = conn.execute("SELECT entity, entity_id, ts, device_id FROM sync_seen").fetchall()
    conn.close()
    return {(r["entity"], r["entity_id"]): (r["ts"], r["device_id"]) for r in rows}


def _is_newer(entry: Dict[str, Any], seen: Dict[Tuple[str, str], Tuple[str, str]]) -> bool:
    key = (entry["entity"], str(entry["entity_id"]))
    current = seen.get(key)
    if current is None:
        return True
    return (entry.get("ts", ""), entry.get("device_id", "")) > current


def _apply_row(conn, entity: str, op: str, payload: Dict[str, Any]) -> bool:
    spec = ENTITIES[entity]
    table, pk = spec["table"], spec["pk"]
    pk_value = payload.get(pk)
    if entity == "settings" and str(pk_value).startswith(("secret.", "sync.")):
        return False
    if op == "delete":
        if pk_value is None:
            return False
        conn.execute(f"DELETE FROM {table} WHERE {pk}=?", (pk_value,))
        return True
    cols = [c for c in spec["cols"] if c in payload]
    if pk not in cols:
        return False
    placeholders = ",".join("?" for _ in cols)
    conn.execute(
        f"INSERT OR REPLACE INTO {table}({','.join(cols)}) VALUES ({placeholders})",
        [payload[c] for c in cols],
    )
    return True


def apply_entries(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Replay remote journal lines locally with last-write-wins.

    Returns a small summary: ``{applied, skipped, cursor}``. Applied lines are
    re-journalled under their *origin* device id so a device in the middle of the
    mesh can relay them onward without ever claiming them as its own.
    """
    applied = skipped = 0
    max_seq = 0
    if not entries:
        return {"applied": 0, "skipped": 0, "cursor": 0}
    conn = db.connect()
    try:
        seen = _seen()
        for entry in entries:
            entity = entry.get("entity")
            if entity not in ENTITIES:
                continue
            max_seq = max(max_seq, int(entry.get("seq") or 0))
            if not _is_newer(entry, seen):
                skipped += 1
                continue
            op = entry.get("op", "upsert")
            payload = entry.get("payload") or {}
            if op == "delete":
                pk = ENTITIES[entity]["pk"]
                if pk not in payload:
                    payload = {pk: entry["entity_id"]}
            try:
                wrote = _apply_row(conn, entity, op, payload)
            except Exception:  # noqa: BLE001 - one bad row must not abort the batch
                skipped += 1
                continue
            if not wrote:
                skipped += 1
                continue
            seen[(entity, str(entry["entity_id"]))] = (
                entry.get("ts", ""),
                entry.get("device_id", ""),
            )
            conn.execute(
                "INSERT OR REPLACE INTO sync_seen(entity, entity_id, ts, device_id) VALUES (?,?,?,?)",
                (entity, str(entry["entity_id"]), entry.get("ts", ""), entry.get("device_id", "")),
            )
            conn.execute(
                "INSERT INTO sync_journal(device_id, entity, entity_id, op, payload, ts) VALUES (?,?,?,?,?,?)",
                (
                    entry.get("device_id", ""),
                    entity,
                    str(entry["entity_id"]),
                    op,
                    json.dumps(payload),
                    entry.get("ts", _now()),
                ),
            )
            applied += 1
        conn.commit()
    finally:
        conn.close()
    return {"applied": applied, "skipped": skipped, "cursor": max_seq}


# --------------------------------------------------------------------------- #
# Transport (LAN peer sync)
# --------------------------------------------------------------------------- #
def _headers(peer: Dict[str, str]) -> Dict[str, str]:
    h = {"Content-Type": "application/json"}
    if peer.get("token"):
        h["X-Jarvis-Sync"] = peer["token"]
    return h


def sync_peer(peer: Dict[str, str], timeout: float = 15.0) -> Dict[str, Any]:
    """Exchange changes with a single peer. Never raises."""
    url = peer["url"].rstrip("/")
    cursors = _cursors()
    cur = cursors.get(url, {"in": 0, "out": 0})
    result: Dict[str, Any] = {"url": url, "ok": False, "applied": 0, "sent": 0}
    try:
        with httpx.Client(timeout=timeout, headers=_headers(peer)) as client:
            resp = client.get(f"{url}/api/sync/changes", params={"since": cur.get("in", 0)})
            resp.raise_for_status()
            data = resp.json()
            entries = data.get("entries") or []
            summary = apply_entries(entries)
            cur["in"] = int(data.get("cursor", cur.get("in", 0)))
            result["applied"] = summary["applied"]

            out_entries, new_out = changes_since(cur.get("out", 0))
            if out_entries:
                push = client.post(
                    f"{url}/api/sync/apply",
                    json={"entries": out_entries, "device": out_entries[-1].get("device_id", "")},
                )
                push.raise_for_status()
                result["sent"] = len(out_entries)
            cur["out"] = new_out
        cursors[url] = cur
        _set_cursors(cursors)
        result["ok"] = True
    except Exception as exc:  # noqa: BLE001 - report, never crash the caller
        result["error"] = str(exc)
    return result


def sync_all(timeout: float = 15.0) -> Dict[str, Any]:
    """Sync with every configured peer; called by the auto loop and SYNC NOW."""
    peers = _read_peers()
    results = [sync_peer(p, timeout=timeout) for p in peers]
    ok = bool(results) and all(r.get("ok") for r in results)
    db.set_setting(K_LAST_SYNC, _now())
    summary = {
        "ok": ok,
        "peers": results,
        "applied": sum(r.get("applied", 0) for r in results),
        "sent": sum(r.get("sent", 0) for r in results),
    }
    db.set_setting(
        K_LAST_RESULT,
        f"applied={summary['applied']} sent={summary['sent']} "
        f"peers={len(results)} ok={ok}",
    )
    return summary


def status() -> Dict[str, Any]:
    cfg = get_config()
    return {
        "enabled": cfg["enabled"],
        "running": _auto_thread is not None and _auto_thread.is_alive(),
        "listener": _listener is not None,
        "port": configured_port(),
        "addresses": [f"http://{ip}:{configured_port()}" for ip in local_ips()],
        "device_id": cfg["device_id"],
        "device_name": cfg["device_name"],
        "interval": cfg["interval"],
        "peers": [
            {"url": p["url"], "token_set": bool(p.get("token"))} for p in _read_peers()
        ],
        "token_set": cfg["token_set"],
        "github_repo": cfg["github_repo"],
        "github_path": cfg["github_path"],
        "github_branch": cfg["github_branch"],
        "github_token_set": cfg["github_token_set"],
        "journal": journal_size(),
        "cursors": _cursors(),
        "last_sync": db.get_setting(K_LAST_SYNC, ""),
        "last_result": db.get_setting(K_LAST_RESULT, ""),
    }


# --------------------------------------------------------------------------- #
# Auto sync loop
# --------------------------------------------------------------------------- #
def _loop() -> None:
    while not _auto_stop.is_set():
        try:
            if db.get_setting(K_ENABLED, "0") in ("1", "true", "True", "yes", "on"):
                if _read_peers():
                    sync_all()
        except Exception:  # noqa: BLE001 - the loop must survive anything
            pass
        try:
            interval = max(MIN_INTERVAL, int(db.get_setting(K_INTERVAL, str(DEFAULT_INTERVAL))))
        except (TypeError, ValueError):
            interval = DEFAULT_INTERVAL
        _auto_stop.wait(interval)


def start_auto() -> bool:
    """Start the background sync loop once. Returns True if this call started it."""
    if os.environ.get("JARVIS_SYNC_AUTO", "1") == "0":
        return False
    global _auto_thread
    with _auto_lock:
        if _auto_thread and _auto_thread.is_alive():
            return False
        _auto_stop.clear()
        _auto_thread = threading.Thread(target=_loop, name="jarvis-sync", daemon=True)
        _auto_thread.start()
        return True


def stop_auto() -> None:
    _auto_stop.set()


# --------------------------------------------------------------------------- #
# LAN listener
#
# The main WebUI/API binds to 127.0.0.1 on purpose: it can run tools and reveal
# masked keys, so it must never face the network. Peers therefore get their own
# tiny listener that speaks only the two sync verbs and always checks the shared
# token. Two devices then swap journal lines directly over Wi-Fi.
# --------------------------------------------------------------------------- #
class _SyncHandler(BaseHTTPRequestHandler):
    server_version = "JarvisSync/1.0"

    def log_message(self, *args) -> None:  # noqa: D102 - silence access logs
        pass

    def _authorized(self) -> bool:
        expected = db.get_setting(K_TOKEN, "")
        if not expected:
            return False  # never serve the LAN without a shared token
        provided = self.headers.get("X-Jarvis-Sync") or parse_qs(urlparse(self.path).query).get(
            "token", [""]
        )[0]
        return provided == expected

    def _json(self, obj: Dict[str, Any], code: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        if path == "/api/sync/health":
            return self._json({"ok": True, "device": device_id(), "device_name": device_name()})
        if not self._authorized():
            return self._json({"ok": False, "error": "unauthorized"}, 401)
        if path == "/api/sync/changes":
            since = int(parse_qs(urlparse(self.path).query).get("since", ["0"])[0] or 0)
            entries, cursor = changes_since(since)
            return self._json(
                {
                    "ok": True,
                    "device": device_id(),
                    "device_name": device_name(),
                    "entries": entries,
                    "cursor": cursor,
                }
            )
        return self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if not self._authorized():
            return self._json({"ok": False, "error": "unauthorized"}, 401)
        if urlparse(self.path).path != "/api/sync/apply":
            return self._json({"ok": False, "error": "not found"}, 404)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (TypeError, ValueError):
            return self._json({"ok": False, "error": "bad json"}, 400)
        summary = apply_entries(payload.get("entries") or [])
        return self._json({"ok": True, **summary})


_listener: Optional[ThreadingHTTPServer] = None


class _SyncServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def server_bind(self) -> None:
        # HTTPServer.server_bind does a reverse-DNS lookup for server_name,
        # which can stall for seconds on a phone with no DNS; skip it.
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port


def start_listener(port: Optional[int] = None) -> Optional[int]:
    """Bind the sync-only listener on the LAN. Returns the port, or None."""
    global _listener
    with _auto_lock:
        if _listener is not None:
            return _listener.server_address[1]
    if port is None:
        port = configured_port()
    try:
        srv = _SyncServer(("0.0.0.0", int(port)), _SyncHandler)
    except OSError:
        return None
    srv.daemon_threads = True
    _listener = srv
    threading.Thread(target=srv.serve_forever, daemon=True, name="jarvis-sync-listener").start()
    return srv.server_address[1]


def stop_listener() -> None:
    global _listener
    with _auto_lock:
        srv, _listener = _listener, None
    if srv is not None:
        try:
            srv.shutdown()
            srv.server_close()
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------- #
# Manual export / import (backup and the GitHub snapshot mirror)
# --------------------------------------------------------------------------- #
def build_snapshot() -> Dict[str, Any]:
    """A full copy of every syncable row, independent of the journal."""
    conn = db.connect()
    try:
        entities: Dict[str, List[Dict[str, Any]]] = {}
        for name, spec in ENTITIES.items():
            rows = conn.execute(f"SELECT {','.join(spec['cols'])} FROM {spec['table']}").fetchall()
            entities[name] = [{c: r[c] for c in spec["cols"]} for r in rows]
    finally:
        conn.close()
    return {
        "version": 1,
        "device_id": device_id(),
        "device_name": device_name(),
        "exported_at": _now(),
        "entities": entities,
    }


def import_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Merge a snapshot produced by :func:`build_snapshot`."""
    entries: List[Dict[str, Any]] = []
    entities = snapshot.get("entities") or {}
    remote_device = snapshot.get("device_id") or "snapshot"
    ts = snapshot.get("exported_at") or _now()
    for name, rows in entities.items():
        if name not in ENTITIES:
            continue
        pk = ENTITIES[name]["pk"]
        for row in rows:
            if row.get(pk) is None:
                continue
            entries.append(
                {
                    "seq": 0,
                    "device_id": remote_device,
                    "entity": name,
                    "entity_id": row[pk],
                    "op": "upsert",
                    "payload": row,
                    "ts": ts,
                }
            )
    summary = apply_entries(entries)
    summary["entities"] = {k: len(v) for k, v in entities.items()}
    return summary


# --------------------------------------------------------------------------- #
# GitHub snapshot mirror (optional fallback transport)
# --------------------------------------------------------------------------- #
def _github_client(token: str) -> httpx.Client:
    return httpx.Client(
        timeout=30.0,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )


def _github_location() -> Tuple[Optional[str], str, str]:
    repo = db.get_setting(K_GITHUB_REPO, "")
    path = db.get_setting(K_GITHUB_PATH, "jarvis-sync.json") or "jarvis-sync.json"
    branch = db.get_setting(K_GITHUB_BRANCH, "main") or "main"
    return (repo or None, path, branch)


def github_push() -> Dict[str, Any]:
    """Write the current snapshot into a GitHub repo file (contents API)."""
    import base64

    repo, path, branch = _github_location()
    token = db.get_setting(K_GITHUB_TOKEN, "")
    if not repo or not token:
        return {"ok": False, "error": "github repo and token are required"}
    snapshot = build_snapshot()
    body = json.dumps(snapshot, indent=2, sort_keys=True).encode("utf-8")
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    try:
        with _github_client(token) as client:
            sha = None
            head = client.get(url, params={"ref": branch})
            if head.status_code == 200:
                sha = head.json().get("sha")
            payload = {
                "message": f"jarvis sync from {snapshot['device_name']} ({snapshot['device_id'][:8]})",
                "content": base64.b64encode(body).decode("ascii"),
                "branch": branch,
            }
            if sha:
                payload["sha"] = sha
            resp = client.put(url, json=payload)
            resp.raise_for_status()
        return {"ok": True, "bytes": len(body), "repo": repo, "path": path}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def github_pull() -> Dict[str, Any]:
    """Read the snapshot file from GitHub and merge it locally."""
    import base64

    repo, path, branch = _github_location()
    token = db.get_setting(K_GITHUB_TOKEN, "")
    if not repo or not token:
        return {"ok": False, "error": "github repo and token are required"}
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    try:
        with _github_client(token) as client:
            resp = client.get(url, params={"ref": branch})
            resp.raise_for_status()
            data = resp.json()
        content = base64.b64decode(data.get("content", "")).decode("utf-8")
        snapshot = json.loads(content)
        summary = import_snapshot(snapshot)
        return {"ok": True, **{k: summary[k] for k in ("applied", "skipped", "entities")}}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
