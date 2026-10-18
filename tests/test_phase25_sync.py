"""Phase 25: cross-surface sync.

Covers the journal, last-write-wins replay (including delete tombstones),
snapshot export/import, the LAN peer client (against a stub peer) and the
``/api/sync/*`` endpoints. Runs against a throwaway SQLite file so the real
``jarvis.db`` is never touched.
"""

import json
import shutil
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fastapi.testclient import TestClient

from jarvis import db, sync
from jarvis.app import app

client = TestClient(app)


def isolate():
    """Point the db layer at a fresh temp file; return a restore callable."""
    tmp = Path(tempfile.mkdtemp(prefix="jarvis-sync-"))
    old = db.DB_PATH
    db.DB_PATH = tmp / "jarvis.db"
    db.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db.init_db()

    def restore():
        db.DB_PATH = old
        shutil.rmtree(tmp, ignore_errors=True)

    return restore


def guard_settings(*keys):
    original = {k: db.get_setting(k) for k in keys}

    def restore():
        for k, v in original.items():
            if v is None:
                db.delete_setting(k)
            else:
                db.set_setting(k, v)

    return restore


# 1
def test_journal_records_writes_but_never_secrets_or_sync_keys():
    restore = isolate()
    try:
        db.set_setting("theme", "dark")
        db.set_setting("secret.openai", "sk-xyz")
        db.set_setting("sync.device_id", "should-not-sync")
        db.remember_db("favourite", "blue")
        db.forget_db("favourite")

        entries, cursor = sync.changes_since(0)
        keys = [(e["entity"], e["entity_id"], e["op"]) for e in entries]
        assert ("settings", "theme", "upsert") in keys
        assert ("memory", "favourite", "upsert") in keys
        assert ("memory", "favourite", "delete") in keys
        assert not any(e["entity_id"].startswith("secret.") for e in entries)
        assert not any(e["device_id"] and e["entity_id"].startswith("sync.") for e in entries)
        assert cursor == entries[-1]["seq"]
        assert sync.journal_size() == len(entries)
    finally:
        restore()
    print("✓ Test 1 PASSED: writes are journalled; secrets and sync keys are not")


# 2
def test_changes_since_paginates_without_gaps():
    restore = isolate()
    try:
        for i in range(5):
            db.remember_db(f"k{i}", i)
        first, cursor = sync.changes_since(0, limit=2)
        second, cursor2 = sync.changes_since(cursor, limit=2)
        third, cursor3 = sync.changes_since(cursor2, limit=2)
        assert len(first) == 2 and len(second) == 2 and len(third) == 1
        seqs = [e["seq"] for e in first + second + third]
        assert seqs == sorted(seqs) and len(set(seqs)) == 5
        empty, same = sync.changes_since(cursor3)
        assert empty == [] and same == cursor3
    finally:
        restore()
    print("✓ Test 2 PASSED: paging through the journal loses nothing")


# 3
def test_apply_is_last_write_wins_with_tombstones_and_idempotent():
    restore = isolate()
    try:
        db.remember_db("colour", "red")
        db.remember_db("colour", "green")  # local newest wins over an older peer

        old = {
            "seq": 1, "device_id": "peerA", "entity": "memory", "entity_id": "colour",
            "op": "upsert", "payload": {"key": "colour", "value": "blue", "updated_at": "2000-01-01T00:00:00+00:00"},
            "ts": "2000-01-01T00:00:00+00:00",
        }
        new = {
            "seq": 2, "device_id": "peerA", "entity": "memory", "entity_id": "colour",
            "op": "upsert", "payload": {"key": "colour", "value": "purple", "updated_at": "2999-01-01T00:00:00+00:00"},
            "ts": "2999-01-01T00:00:00+00:00",
        }
        assert sync.apply_entries([old])["applied"] == 0  # older: skipped
        assert sync.apply_entries([new])["applied"] == 1  # newer: applied
        assert db.recall_db("colour") == "purple"

        again = sync.apply_entries([new])  # replaying is a no-op
        assert again["applied"] == 0 and again["skipped"] == 1

        tomb = {
            "seq": 3, "device_id": "peerA", "entity": "memory", "entity_id": "colour",
            "op": "delete", "payload": {}, "ts": "3000-01-01T00:00:00+00:00",
        }
        assert sync.apply_entries([tomb])["applied"] == 1
        assert db.recall_db("colour") is None
    finally:
        restore()
    print("✓ Test 3 PASSED: last-write-wins, tombstones remove, replay is idempotent")


# 4
def test_apply_refuses_to_overwrite_secrets_or_sync_config():
    restore = isolate()
    try:
        db.set_setting("secret.openai", "keep-me")
        db.set_setting("sync.device_id", "mine")
        entries = [
            {
                "seq": 1, "device_id": "evil", "entity": "settings", "entity_id": "secret.openai",
                "op": "upsert", "payload": {"key": "secret.openai", "value": "stolen"},
                "ts": "2999-01-01T00:00:00+00:00",
            },
            {
                "seq": 2, "device_id": "evil", "entity": "settings", "entity_id": "sync.device_id",
                "op": "upsert", "payload": {"key": "sync.device_id", "value": "hijacked"},
                "ts": "2999-01-01T00:00:00+00:00",
            },
        ]
        sync.apply_entries(entries)
        assert db.get_setting("secret.openai") == "keep-me"
        assert db.get_setting("sync.device_id") == "mine"
    finally:
        restore()
    print("✓ Test 4 PASSED: a peer cannot overwrite secrets or this device's identity")


# 5
def test_snapshot_round_trips_every_entity():
    restore = isolate()
    try:
        db.remember_db("planet", "earth")
        db.add_task_db("t1", "write tests")
        db.add_note_db("n1", "hello", ["a"])
        db.save_message("s1", "user", "hi there")
        snap = sync.build_snapshot()
        assert set(snap["entities"]) >= {"settings", "memory", "tasks", "notes", "messages"}

        # a brand-new device imports the snapshot and sees the same rows
        restore2 = isolate()
        try:
            summary = sync.import_snapshot(snap)
            assert summary["applied"] >= 4
            assert db.recall_db("planet") == "earth"
            assert any(t["id"] == "t1" for t in db.get_tasks_db())
            assert any(m["msg_id"] for m in db.list_messages_db("s1"))
        finally:
            restore2()
    finally:
        restore()
    print("✓ Test 5 PASSED: snapshot export/import reproduces rows on a new device")


class PeerStub(BaseHTTPRequestHandler):
    entries = []
    pushed = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps(
            {"ok": True, "device": "peerB", "entries": PeerStub.entries, "cursor": 7}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        PeerStub.pushed.append(json.loads(self.rfile.read(length) or b"{}"))
        body = json.dumps({"ok": True, "applied": 1, "cursor": 0}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve_peer():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), PeerStub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


# 6
def test_peer_sync_pulls_applies_and_pushes():
    restore = isolate()
    srv, port = serve_peer()
    try:
        PeerStub.entries = [
            {
                "seq": 3, "device_id": "peerB", "entity": "notes", "entity_id": "n-remote",
                "op": "upsert",
                "payload": {"note_id": "n-remote", "content": "from peer", "tags": "[]",
                            "created_at": "2026-01-01T00:00:00+00:00"},
                "ts": "2026-01-01T00:00:00+00:00",
            }
        ]
        PeerStub.pushed = []
        db.add_note_db("n-local", "mine")  # something to push back

        peer = {"url": f"http://127.0.0.1:{port}", "token": ""}
        result = sync.sync_peer(peer)
        assert result["ok"], result
        assert result["applied"] == 1
        assert any(n["id"] == "n-remote" for n in db.get_notes_db())

        assert result["sent"] >= 1
        assert PeerStub.pushed, "peer never received our changes"
        sent_ids = [e["entity_id"] for e in PeerStub.pushed[0]["entries"]]
        assert "n-local" in sent_ids

        cursors = json.loads(db.get_setting("sync.cursors"))
        assert cursors[peer["url"]]["in"] == 7
        assert cursors[peer["url"]]["out"] >= result["sent"]
    finally:
        srv.shutdown()
        restore()
    print("✓ Test 6 PASSED: LAN peer pull + push round-trips through the API")


# 7
def test_sync_status_settings_and_token_endpoints():
    restore = isolate()
    guard = guard_settings("sync.enabled", "sync.device_name", "sync.interval", "sync.token", "sync.port")
    try:
        st = client.get("/api/sync/status").json()
        assert st["ok"] and st["device_id"]

        r = client.post("/api/sync/settings", json={"enabled": True, "device_name": "laptop"}).json()
        assert r["ok"] and r["config"]["enabled"] is True
        assert r["status"]["enabled"] is True
        assert r["status"]["device_name"] == "laptop"

        r = client.post("/api/sync/settings", json={"port": 9001, "interval": 10}).json()
        assert r["status"]["port"] == 9001 and r["status"]["interval"] == 10

        # enabling created a token, and the token endpoint can reveal/rotate it
        tok = client.post("/api/sync/token?action=get").json()["token"]
        assert tok
        assert db.get_setting("sync.token") == tok
        rotated = client.post("/api/sync/token?action=rotate").json()["token"]
        assert rotated and rotated != tok
    finally:
        guard()
        restore()
    print("✓ Test 7 PASSED: status/settings/token endpoints behave")


# 8
def test_changes_and_apply_endpoints_enforce_token():
    restore = isolate()
    guard = guard_settings("sync.token")
    try:
        db.set_setting("sync.token", "s3cret")
        db.remember_db("peekaboo", "1")

        assert client.get("/api/sync/changes").status_code == 401
        ok = client.get("/api/sync/changes", headers={"X-Jarvis-Sync": "s3cret"})
        assert ok.status_code == 200 and ok.json()["entries"]

        assert client.post("/api/sync/apply", json={"entries": []}).status_code == 401

        entry = {
            "seq": 1, "device_id": "peerC", "entity": "memory", "entity_id": "gift",
            "op": "upsert",
            "payload": {"key": "gift", "value": "cake", "updated_at": "2999-01-01T00:00:00+00:00"},
            "ts": "2999-01-01T00:00:00+00:00",
        }
        ok = client.post(
            "/api/sync/apply", json={"entries": [entry]}, headers={"X-Jarvis-Sync": "s3cret"}
        )
        assert ok.status_code == 200 and ok.json()["applied"] == 1
        assert db.recall_db("gift") == "cake"
    finally:
        guard()
        restore()
    print("✓ Test 8 PASSED: peer endpoints require the shared token")


# 9
def test_auto_loop_starts_once_and_is_inert_without_peers():
    sync.start_auto()
    assert sync.start_auto() is False  # second call is a no-op
    st = sync.status()
    assert st["running"] is True
    assert sync.sync_all()["peers"] == []  # no peers configured → nothing to do
    sync.stop_auto()
    print("✓ Test 9 PASSED: background sync loop starts once and idles safely")


# 10
def test_lan_listener_serves_token_protected_sync():
    restore = isolate()
    guard = guard_settings("sync.token", "sync.port")
    try:
        sync.stop_listener()
        db.set_setting("sync.token", "lan-secret")
        port = sync.start_listener(port=0)
        assert port, "listener failed to bind"

        base = f"http://127.0.0.1:{port}"
        # no token → rejected
        import httpx as _httpx

        assert _httpx.get(f"{base}/api/sync/changes").status_code == 401
        # health is open, so a peer can discover us before authenticating
        assert _httpx.get(f"{base}/api/sync/health").json()["device"]

        db.add_note_db("n-lan", "over the wire")
        peer = {"url": base, "token": "lan-secret"}
        result = sync.sync_peer(peer)
        assert result["ok"], result
        # the peer is this same device, so our note is already present and the
        # journal replays idempotently (applied may be >0 but never errors)
        assert any(n["id"] == "n-lan" for n in db.get_notes_db())
        assert sync.status()["listener"] is True
    finally:
        sync.stop_listener()
        guard()
        restore()
    print("✓ Test 10 PASSED: LAN listener requires the token and round-trips")
