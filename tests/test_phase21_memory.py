"""Phase 21 — Memory ingestion + import.

Exercises the heuristic extractor, de-duplication, ranked search, file /
JSON / legacy import, export, the HTTP API, the three new tools and the
chat auto-capture setting. Each test runs against an isolated temp SQLite
file so results are deterministic and repeatable (the runner has no
pytest fixtures, so isolation is done with an explicit context manager).

No network: the LLM extraction path is exercised by temporarily swapping
``jarvis.llm.complete`` for a fake coroutine.
"""

import asyncio
import contextlib
import json
import shutil
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from jarvis import assistant, db, llm, memory_ingest, tools
from jarvis.app import app

AUTO_INGEST_KEY = "memory.auto_ingest"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def fresh_memory():
    """Point the DB at a throwaway SQLite file for the duration of a test."""
    original = db.DB_PATH
    tmp = Path(tempfile.mkdtemp(prefix="jv21-", dir="."))
    db.DB_PATH = tmp / "jarvis.db"
    db.init_db()
    try:
        yield tmp
    finally:
        db.DB_PATH = original
        shutil.rmtree(tmp, ignore_errors=True)


def client():
    return TestClient(app)


def temp_file(directory, name, content, mode="w"):
    p = Path(directory) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    if "b" in mode:
        p.write_bytes(content)
    else:
        p.write_text(content, encoding="utf-8")
    return p


# 1
def test_new_item_builds_hash_and_dedupes():
    with fresh_memory():
        a = memory_ingest.new_item("My name is Husayn.", source="t1")
        assert a["hash"] and a["item_id"].startswith("m")
        assert len(a["hash"]) == 40

        first = memory_ingest.store_items([a])
        assert first == {"added": 1, "skipped": 0}

        # exact duplicate
        dup = memory_ingest.new_item("My name is Husayn.", source="t1")
        assert memory_ingest.store_items([dup])["skipped"] == 1

        # same text, different case/whitespace still de-dupes
        variant = memory_ingest.new_item("  my   name   is husayn. ", source="t2")
        assert memory_ingest.store_items([variant])["skipped"] == 1

        assert memory_ingest.stats()["total"] == 1


# 2
def test_heuristic_extraction_facts_notes_and_tags():
    text = """
# Profile
My name is Husayn.
- I prefer Urdu replies.
editor: vim
## Tools
I use vim every day.
```
def ignored(): pass
import os
```
tiny
"""
    with fresh_memory():
        items = memory_ingest.extract_facts(text, source="notes.md", tags="base")
        texts = [i["text"] for i in items]
        keys = [i["key"] for i in items]

        assert "name: Husayn." in texts          # "my X is Y" fact
        assert "i prefer: Urdu replies." in texts  # preference fact
        assert any(k == "editor" for k in keys)  # "key: value" fact
        # code fence and bare code lines are skipped
        assert not any("def ignored" in t for t in texts)
        assert not any("import os" in t for t in texts)

        by_key = {i["key"]: i for i in items}
        assert "profile" in by_key["name"].get("tags", [])  # heading tag
        assert "base" in by_key["name"].get("tags", [])     # caller tag
        assert all(i["source"] == "notes.md" for i in items)
        assert all(i["kind"] in ("fact", "note") for i in items)


# 3
def test_ingest_text_counts_and_tags_from_hashtags():
    with fresh_memory():
        r = memory_ingest.ingest_text(
            "My phone number is 555. #urgent\nMy phone number is 555.",
            source="chat",
            tags="contacts",
        )
        assert r["added"] >= 1
        assert r["skipped"] >= 1  # the duplicate line is skipped
        found = memory_ingest.search("phone")
        assert found, "expected the phone fact to be searchable"
        assert "contacts" in found[0]["tags"]


# 4
def test_clause_splitting_when_every_clause_is_a_fact():
    with fresh_memory():
        # one line, two clean facts
        items = memory_ingest.extract_facts(
            "My name is Zara and I live in Karachi.", source="chat"
        )
        assert sorted(i["key"] for i in items) == ["i-live-in", "name"]
        assert all(i["kind"] == "fact" for i in items)

        # conjunction joining nouns -> no bogus split
        items = memory_ingest.extract_facts("I like pizza and salad.", source="chat")
        assert len(items) == 1 and items[0]["kind"] == "fact"
        assert "salad" in items[0]["text"]

        # plain sentence with no clean clause split stays a single note
        items = memory_ingest.extract_facts("Bought milk and eggs.", source="chat")
        assert len(items) == 1 and items[0]["kind"] == "note"


# 5
def test_search_ranking_key_beats_text():
    with fresh_memory():
        via_key = memory_ingest.new_item("skill: python", key="python", source="cv")
        via_text = memory_ingest.new_item("I once wrote that python is fun", source="chat")
        memory_ingest.store_items([via_key, via_text])

        hits = memory_ingest.search("python")
        assert [h["source"] for h in hits][:1] == ["cv"]
        assert hits[0]["key"] == "python"


# 6
def test_search_tag_and_source_filters():
    with fresh_memory():
        memory_ingest.store_items(
            [
                memory_ingest.new_item("meeting at 5", source="cal", tags="work"),
                memory_ingest.new_item("buy milk", source="home", tags="errands"),
            ]
        )
        assert len(memory_ingest.search("meeting", tags="work")) == 1
        assert memory_ingest.search("", tags="work")[0]["source"] == "cal"
        only_home = memory_ingest.search("", source="home")
        assert all(i["source"] == "home" for i in only_home)
        assert len(only_home) == 1


# 7
def test_llm_extraction_parses_json_and_falls_back():
    fake_reply = json.dumps(
        [
            {"key": "language", "value": "Urdu", "tags": ["speak"]},
            {"key": "city", "value": "Lahore"},
        ]
    )
    original = llm.complete

    async def fake_complete(*args, **kwargs):
        return fake_reply, "fake-llm"

    async def broken_complete(*args, **kwargs):
        raise RuntimeError("no providers available")

    with fresh_memory():
        llm.complete = fake_complete
        try:
            result = asyncio.run(
                memory_ingest.aingest_text(
                    "I speak Urdu and live in Lahore.", mode="llm", source="chat"
                )
            )
        finally:
            llm.complete = original
        assert result["mode"] == "llm"
        assert result["added"] == 2
        assert {i["key"] for i in memory_ingest.search("")} >= {"language", "city"}

        # provider blows up -> silently fall back to the heuristic pass
        llm.complete = broken_complete
        try:
            result = asyncio.run(
                memory_ingest.aingest_text(
                    "My name is Sadia.", mode="llm", source="chat"
                )
            )
        finally:
            llm.complete = original
        assert result["mode"] == "heuristic"
        assert any("Sadia" in i["text"] for i in memory_ingest.search("Sadia"))


# 8
def test_export_import_roundtrip():
    with fresh_memory():
        memory_ingest.ingest_text("My name is Aisha.\ncity: Karachi", source="notes")
        exported = memory_ingest.export_items()
        assert len(exported) >= 2
        assert all("text" in row and "hash" not in row for row in exported)

        assert memory_ingest.clear_all() >= 2
        assert memory_ingest.stats()["total"] == 0

        result = memory_ingest.import_items(exported)
        assert result["added"] == len(exported)
        # re-import of the same payload is a no-op
        again = memory_ingest.import_items(exported)
        assert again["added"] == 0 and again["skipped"] == len(exported)
        assert memory_ingest.stats()["total"] == len(exported)


# 9
def test_import_file_json_csv_markdown():
    with fresh_memory() as tmp:
        md = temp_file(
            tmp, "notes.md",
            "# Recipes\npasta needs salt.\nI like spicy food.\n",
        )
        r = memory_ingest.import_file(str(md))
        assert r["added"] >= 2
        assert r["mode"] == "file"

        csv_file = temp_file(
            tmp, "contacts.csv",
            "key,value,tags\nphone,555,contacts\nemail,me@test.com,contacts\n",
        )
        r = memory_ingest.import_file(str(csv_file))
        assert r["added"] == 2
        assert all(i["source"] == "contacts.csv" for i in memory_ingest.search("", source="contacts.csv"))

        js = temp_file(
            tmp, "facts.json",
            json.dumps({"items": [{"text": "pet: cat", "key": "pet", "tags": ["home"]}]}),
        )
        r = memory_ingest.import_file(str(js))
        assert r["added"] == 1
        assert memory_ingest.search("pet")[0]["tags"] == ["home"]


# 10
def test_import_file_rejects_unsafe_path_and_missing_file():
    with fresh_memory() as tmp:
        try:
            memory_ingest.import_file("/etc/hosts")
        except memory_ingest.MemoryError as exc:
            assert "not allowed" in str(exc)
        else:
            raise AssertionError("unsafe path must be rejected")

        try:
            memory_ingest.import_file(str(Path(tmp) / "does-not-exist.md"))
        except memory_ingest.MemoryError as exc:
            assert "file not found" in str(exc)
        else:
            raise AssertionError("missing file must raise MemoryError")


# 11
def test_import_legacy_key_value_memory():
    with fresh_memory():
        db.remember_db("fav_color", "teal")
        db.remember_db("session:theme", {"value": "dark"})

        result = memory_ingest.import_legacy_memory()
        assert result["added"] == 2
        items = memory_ingest.search("", source="legacy")
        assert len(items) == 2
        assert any("fav_color" in i["text"] for i in items)
        # JSON-serialised legacy values are flattened into the text
        assert any("dark" in i["text"] for i in items)


# 12
def test_delete_item_and_source_and_clear():
    with fresh_memory():
        memory_ingest.ingest_text("one two three four.\nalpha beta gamma five.", source="keep")
        memory_ingest.ingest_text("unique fact here only once.", source="drop")

        target = memory_ingest.search("unique fact")[0]
        assert memory_ingest.delete_item(target["item_id"]) is True
        assert memory_ingest.delete_item("mdoesnotexist") is False

        removed = memory_ingest.delete_source("drop")
        assert removed >= 0
        assert memory_ingest.search("", source="drop") == []
        assert memory_ingest.stats()["total"] >= 1

        assert memory_ingest.clear_all() >= 1
        assert memory_ingest.stats()["total"] == 0


# 13
def test_memory_endpoints_crud_and_ingest():
    with fresh_memory():
        c = client()

        # list starts empty
        r = c.get("/api/memory")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 0 and body["stats"]["total"] == 0

        # add one item
        r = c.post(
            "/api/memory",
            json={"text": "My name is Bilal.", "source": "ui", "tags": "people"},
        )
        assert r.status_code == 200
        added = r.json()
        assert added["ok"] and added["added"] == 1
        item_id = added["item"]["item_id"]

        # bad request when text missing
        assert c.post("/api/memory", json={"text": "  "}).status_code == 400

        # extract a block of text
        r = c.post(
            "/api/memory/ingest",
            json={"text": "I live in Peshawar.\ncity: Peshawar", "mode": "heuristic"},
        )
        assert r.status_code == 200
        assert r.json()["added"] >= 1

        # unknown extraction mode -> 400
        assert c.post("/api/memory/ingest", json={"text": "x y", "mode": "telepathy"}).status_code == 400

        # search
        r = c.get("/api/memory", params={"query": "name"})
        assert r.status_code == 200
        assert any("Bilal" in i["text"] for i in r.json()["items"])

        # delete: unknown id 404, known id 200
        assert c.delete("/api/memory/mnope123").status_code == 404
        r = c.delete(f"/api/memory/{item_id}")
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # stats endpoint
        r = c.get("/api/memory/stats")
        assert r.status_code == 200
        assert r.json()["ok"] is True and "sources" in r.json()


# 14
def test_memory_endpoints_import_export_delete_source():
    with fresh_memory() as tmp:
        c = client()

        # inline items import
        r = c.post(
            "/api/memory/import",
            json={"items": [{"text": "pet: dog", "key": "pet"}], "source": "json"},
        )
        assert r.status_code == 200 and r.json()["added"] == 1

        # file import
        f = temp_file(tmp, "bulk.md", "hobby: chess.\nI like long walks.\n")
        r = c.post("/api/memory/import", json={"path": str(f)})
        assert r.status_code == 200 and r.json()["added"] >= 2

        # legacy import (empty legacy table is fine)
        r = c.post("/api/memory/import", json={"legacy": True})
        assert r.status_code == 200 and "added" in r.json()

        # nothing provided -> 400
        assert c.post("/api/memory/import", json={}).status_code == 400
        # unsafe path -> 400
        r = c.post("/api/memory/import", json={"path": "/etc/hosts"})
        assert r.status_code == 400 and "not allowed" in r.json()["error"]

        # export
        r = c.get("/api/memory/export")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] and data["count"] >= 3
        assert isinstance(data["items"], list)
        assert "jarvis-memory.json" in r.headers.get("content-disposition", "")

        # delete by source
        r = c.post("/api/memory/delete-source", json={"source": "json"})
        assert r.status_code == 200 and r.json()["removed"] == 1
        assert c.post("/api/memory/delete-source", json={"source": ""}).status_code == 400


# 15
def test_memory_tools_registered_and_run():
    with fresh_memory() as tmp:
        reg = tools.get_enhanced_registry()
        names = {t["name"] for t in reg.list_tools()}
        assert {"memory.ingest", "memory.search", "memory.import"} <= names

        r = reg.execute("memory.ingest", text="skill: go", source="tools")
        assert r.success, r.error
        assert r.result["added"] == 1

        r = reg.execute("memory.search", query="skill")
        assert r.success
        assert r.result["count"] >= 1

        # empty text is rejected
        r = reg.execute("memory.ingest", text="   ")
        assert r.success is False and "required" in r.error

        # import a file
        f = temp_file(tmp, "t.md", "one more fact here.\n")
        r = reg.execute("memory.import", path=str(f))
        assert r.success, r.error
        assert r.result["added"] >= 1

        # unknown tool stays 404-ish
        assert reg.execute("memory.nope").success is False


# 16
def test_memory_tools_respect_permission_system():
    from jarvis.permissions import PermissionManager

    perm = PermissionManager()
    assert perm.is_allowed("memory.read") is True
    assert perm.is_allowed("memory.write") is True
    # memory.write is not in the confirmation-required set
    assert perm.needs_confirmation("memory.write") is False

    reg = tools.get_enhanced_registry()
    tool = reg.get("memory.ingest")
    assert tool is not None and tool.permissions == ["memory.write"]
    assert reg.get("memory.import").resource_kwarg == "path"


# 17
def test_auto_ingest_setting_and_assistant_capture():
    with fresh_memory():
        # off by default
        assert memory_ingest.is_auto_ingest_enabled() is False
        off = memory_ingest.auto_ingest_turn("My name is Zara.")
        assert off["added"] == 0 and off["enabled"] is False
        assert memory_ingest.search("Zara") == []

        # turn it on
        memory_ingest.set_auto_ingest(True)
        assert memory_ingest.is_auto_ingest_enabled() is True
        assert memory_ingest.stats()["auto_ingest"] is True

        on = memory_ingest.auto_ingest_turn("My name is Zara.", session="s1")
        assert on["enabled"] is True
        assert any("Zara" in i["text"] for i in memory_ingest.search("Zara"))

        # assistant._record passively captures the user's turn
        a = assistant.Assistant(mode="basic")
        a._record("My name is Zara.", "noted")
        memory_ingest.set_auto_ingest(False)
        a._record("My name is Qasim.", "noted")
        names = {i["text"] for i in memory_ingest.search("name")}
        assert any("Zara" in n for n in names)
        assert not any("Qasim" in n for n in names)


# 18
def test_ui_ships_memory_tab_and_wires_endpoints():
    root = Path(__file__).resolve().parent.parent
    html = (root / "web" / "index.html").read_text(encoding="utf-8")
    js = (root / "web" / "app.js").read_text(encoding="utf-8")
    css = (root / "web" / "style.css").read_text(encoding="utf-8")

    assert 'data-tab="memory"' in html
    assert 'id="tab-memory"' in html
    for marker in ("mem-query", "mem-list", "mem-add", "mem-ingest", "mem-import-file", "mem-export"):
        assert marker in html, marker

    for endpoint in ("/api/memory?", "/api/memory/ingest", "/api/memory/import",
                     "/api/memory/export", "/api/memory/delete-source"):
        assert endpoint in js, endpoint
    assert "loadMemory()" in js and "mem-auto" in js
    assert ".mem-card" in css and ".mem-chip" in css

    # syntax-check the JS module when node is available (best effort)
    import subprocess

    if shutil.which("node"):
        out = subprocess.run(
            ["node", "--check", str(root / "web" / "app.js")],
            capture_output=True,
            text=True,
        )
        assert out.returncode == 0, out.stderr
