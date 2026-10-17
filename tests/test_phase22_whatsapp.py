"""Phase 22 — WhatsApp bridge: live reading, per-chat rules, replies, import.

The Java listener/bridge is replaced by a fake that mirrors the JSON-in/
JSON-out static API, and the chat provider is a fake ``llm.complete`` so no
network is touched. Isolation uses a throwaway SQLite file (the runner has no
pytest fixtures), same pattern as Phase 21.
"""

import asyncio
import contextlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from jarvis import db, llm, whatsapp
from jarvis.app import app

EXPORT_SAMPLE = """12/03/2024, 5:04 PM - Faraz: salam bhai, kaise ho?
12/03/2024, 5:05 PM - You: theek hoon, aap sunao
12/03/2024, 5:06 PM - Faraz: ek kaam tha
baat kar sakta hun?
13/03/2024, 09:00 - Faraz: <Media omitted>
13/03/2024, 09:01 - Messages and calls are end-to-end encrypted.
12/31/2024, 17:04 - Ali: saal mubarak
14 March 2024, 17:04 - Faraz: long date line
March 15, 2024, 5:04 PM - Faraz: month first line
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def fresh_wa():
    """Isolated DB + clean module state for one test."""
    original = db.DB_PATH
    tmp = Path(tempfile.mkdtemp(prefix="jv22-", dir="."))
    db.DB_PATH = tmp / "jarvis.db"
    db.init_db()
    whatsapp.clear_backend()
    whatsapp.reset_state()
    try:
        yield tmp
    finally:
        db.DB_PATH = original
        whatsapp.clear_backend()
        whatsapp.reset_state()
        shutil.rmtree(tmp, ignore_errors=True)


class FakeWaBridge:
    """Mirrors ai.jarvis.assistant.whatsapp.WhatsAppBridge (static methods)."""

    def __init__(self):
        self.listener = True
        self.targets = []
        self.sent = []
        self.fail_reply = None

    def status(self):
        return {
            "ok": True,
            "supported": True,
            "listener": self.listener,
            "targets": list(self.targets),
        }

    def reply(self, request_json):
        request = json.loads(request_json)
        if self.fail_reply:
            return {"ok": False, "error": self.fail_reply}
        self.sent.append(request)
        return {"ok": True, "chat": request["chat"], "provider": "whatsapp_reply"}


@contextlib.contextmanager
def fake_provider(reply="theek hai, batao"):
    """Swap jarvis.llm for a deterministic no-network chat provider."""
    original_has = llm.has_provider
    original_complete = llm.complete
    calls = []

    async def complete(messages, **kwargs):
        calls.append({"messages": messages, "kwargs": kwargs})
        return reply, "fake-llm"

    llm.has_provider = lambda: True
    llm.complete = complete
    try:
        yield calls
    finally:
        llm.has_provider = original_has
        llm.complete = original_complete


def client():
    return TestClient(app)


def temp_export(directory, name, content):
    p = Path(directory) / name
    p.write_text(content, encoding="utf-8")
    return p


# 1
def test_status_offline_is_honest():
    with fresh_wa():
        data = whatsapp.status_payload()
        assert data["ok"] is True and data["supported"] is False
        assert data["listen"] is True and data["auto_reply"] is False
        assert data["cooldown"] == 60 and data["rules"] == {}
        assert data["listener"] is False and data["targets"] == []
        assert data["messages"] == 0 and data["chats"] == 0
        assert "Android app" in data["note"]
        assert whatsapp.is_supported() is False


# 2
def test_bridge_status_and_send_require_android():
    with fresh_wa():
        # no bridge at all
        assert whatsapp.bridge_status() == {"supported": False}
        try:
            whatsapp.send_reply("Faraz", "hello")
            assert False, "expected WhatsAppError"
        except whatsapp.WhatsAppError as exc:
            assert exc.status == 409 and "Android app" in str(exc)

        fake = FakeWaBridge()
        whatsapp.set_backend(fake)
        assert whatsapp.is_supported() is True
        status = whatsapp.bridge_status()
        assert status["supported"] is True and status["listener"] is True

        # input validation
        try:
            whatsapp.send_reply("", "x")
            assert False
        except whatsapp.WhatsAppError:
            pass
        try:
            whatsapp.send_reply("Faraz", "  ")
            assert False
        except whatsapp.WhatsAppError:
            pass

        data = whatsapp.send_reply("Faraz", "salam")
        assert data["ok"] is True
        assert fake.sent == [{"chat": "Faraz", "text": "salam"}]
        # outbound message recorded so history/cooldown see it
        history = whatsapp.history("Faraz")
        assert history["count"] == 1
        assert history["messages"][0]["direction"] == "out"


# 3
def test_record_message_dedupes_by_minute_hash():
    with fresh_wa():
        first = whatsapp.record_message("Faraz", "salam!", ts="2024-03-12 17:04")
        dup = whatsapp.record_message("Faraz", "salam!", ts="2024-03-12 17:04")
        other = whatsapp.record_message("Faraz", "salam!", ts="2024-03-12 17:05")
        assert first is True and dup is False and other is True
        # whitespace variations of the *text* still dedupe inside the minute
        squashed = whatsapp.record_message("Faraz", "  salam! ", ts="2024-03-12 17:04")
        assert squashed is False
        assert db.count_wa_messages_db() == 2
        # empty chat/text never store
        assert whatsapp.record_message("", "x") is False
        assert whatsapp.record_message("Faraz", "   ") is False


# 4
def test_record_event_gated_by_listen_and_validation():
    with fresh_wa():
        r = whatsapp.record_event({"chat": "Ali", "text": "hi"})
        assert r["ok"] and r["stored"] is True and r["chat"] == "Ali"

        whatsapp.apply_settings(listen=False)
        r = whatsapp.record_event({"chat": "Ali", "text": "hi again"})
        assert r["stored"] is False and "disabled" in r["reason"]

        whatsapp.apply_settings(listen=True)
        try:
            whatsapp.record_event({"text": "no chat"})
            assert False
        except whatsapp.WhatsAppError:
            pass
        r = whatsapp.record_event({"chat": "Ali", "text": "   "})
        assert r["stored"] is False

        # ts_ms (epoch millis) normalises to a sortable stamp
        r = whatsapp.record_event({"chat": "Ali", "text": "ts test", "ts_ms": 1710268800000})
        assert r["stored"] is True
        msgs = whatsapp.history("Ali")["messages"]
        stamped = [m for m in msgs if m["text"] == "ts test"][0]
        assert stamped["ts"].startswith("20")


# 5
def test_settings_validation_and_rules_roundtrip():
    with fresh_wa():
        effective = whatsapp.apply_settings(
            listen=True, auto_reply=True, rules={"Faraz": "auto", "Ali": "suggest"}, cooldown=30
        )
        assert effective == {
            "listen": True,
            "auto_reply": True,
            "cooldown": 30,
            "rules": {"Faraz": "auto", "Ali": "suggest"},
        }
        assert whatsapp.rule_for("Faraz") == "auto"
        assert whatsapp.rule_for("nobody") == "off"

        for bad in ({"Faraz": "yell"}, {"": "auto"}, "not-a-dict"):
            try:
                whatsapp.apply_settings(rules=bad)
                assert False, f"expected rejection of {bad!r}"
            except whatsapp.WhatsAppError:
                pass
        try:
            whatsapp.apply_settings(cooldown=-5)
            assert False
        except whatsapp.WhatsAppError:
            pass
        try:
            whatsapp.apply_settings(cooldown=999999)
            assert False
        except whatsapp.WhatsAppError:
            pass

        # corrupt rules setting is tolerated
        db.set_setting(whatsapp.RULES_SETTING, "{not json")
        assert whatsapp.get_rules() == {}
        db.set_setting(whatsapp.RULES_SETTING, json.dumps({"A": "off", "B": "bad", "C": "auto"}))
        assert whatsapp.get_rules() == {"A": "off", "C": "auto"}


# 6
def test_should_reply_rule_matrix():
    with fresh_wa():
        fake = FakeWaBridge()
        whatsapp.set_backend(fake)
        whatsapp.apply_settings(auto_reply=True, cooldown=0)

        assert whatsapp.should_reply("Faraz")["ok"] is False  # no rule
        whatsapp.apply_settings(rules={"Faraz": "suggest"})
        assert whatsapp.should_reply("Faraz") == {
            "ok": True, "mode": "suggest", "reason": "",
        }

        # auto needs the master switch
        whatsapp.apply_settings(auto_reply=False, rules={"Faraz": "auto"})
        r = whatsapp.should_reply("Faraz")
        assert r["ok"] is False and "disabled" in r["reason"]

        # auto needs the Android reply target
        whatsapp.apply_settings(auto_reply=True)
        r = whatsapp.should_reply("Faraz")
        assert r["ok"] is False and "no open reply target" in r["reason"]

        fake.targets = ["Faraz"]
        assert whatsapp.should_reply("Faraz")["ok"] is True

        # listener must be running
        fake.listener = False
        r = whatsapp.should_reply("Faraz")
        assert r["ok"] is False and "listener" in r["reason"]
        fake.listener = True

        # listen master off blocks everything
        whatsapp.apply_settings(listen=False)
        r = whatsapp.should_reply("Faraz")
        assert r["ok"] is False and "listening" in r["reason"]
        whatsapp.apply_settings(listen=True)

        # cooldown after a live outbound message
        whatsapp.apply_settings(rules={"Faraz": "auto"}, cooldown=3600)
        whatsapp.record_message("Faraz", "auto reply", direction="out", source="live")
        r = whatsapp.should_reply("Faraz")
        assert r["ok"] is False and "cooldown" in r["reason"]
        whatsapp.apply_settings(cooldown=0)
        assert whatsapp.should_reply("Faraz")["ok"] is True


# 7
def test_generate_reply_uses_transcript_and_style():
    with fresh_wa():
        whatsapp.record_message("Faraz", "salam bhai kaise ho", ts="2024-03-12 17:00")
        whatsapp.record_message(
            "Faraz", "theek hai bhai", direction="out", ts="2024-03-12 17:01"
        )
        with fake_provider("bas theek, aur batao") as calls:
            text = asyncio.run(whatsapp.generate_reply("Faraz"))
        assert text == "bas theek, aur batao"
        assert len(calls) == 1
        system = calls[0]["messages"][0]["content"]
        user = calls[0]["messages"][1]["content"]
        assert "WhatsApp" in system and "2 short lines" in system
        assert "salam bhai kaise ho" in user and "theek hai bhai" in user

        # no provider configured -> honest 409
        try:
            asyncio.run(whatsapp.generate_reply("Faraz"))
            assert False
        except whatsapp.WhatsAppError as exc:
            assert exc.status == 409 and "provider" in str(exc)

        try:
            asyncio.run(whatsapp.generate_reply("  "))
            assert False
        except whatsapp.WhatsAppError:
            pass

        # empty chat -> cannot draft
        try:
            asyncio.run(whatsapp.generate_reply("Ghost"))
            assert False
        except whatsapp.WhatsAppError:
            pass


# 8
def test_handle_event_suggest_and_auto_modes():
    with fresh_wa():
        fake = FakeWaBridge()
        whatsapp.set_backend(fake)

        # suggest mode: stores a draft, never sends
        whatsapp.apply_settings(rules={"Faraz": "suggest"})
        with fake_provider("salam! kya haal hai"):
            result = asyncio.run(
                whatsapp.handle_event({"chat": "Faraz", "text": "kaisay ho?"})
            )
        assert result["stored"] is True
        assert result["reply"]["mode"] == "suggest" and result["reply"]["ok"] is True
        assert result["suggestion"] == "salam! kya haal hai"
        assert fake.sent == []
        assert whatsapp.get_suggestion("Faraz")["text"] == "salam! kya haal hai"

        # duplicate notification does not trigger a second draft
        with fake_provider("second draft") as calls:
            result = asyncio.run(
                whatsapp.handle_event({"chat": "Faraz", "text": "kaisay ho?"})
            )
        assert result["stored"] is False and len(calls) == 0

        # auto mode: sends through the bridge and records the outbound
        whatsapp.apply_settings(auto_reply=True, cooldown=0, rules={"Faraz": "auto"})
        fake.targets = ["Faraz"]
        with fake_provider("theek, shukriya"):
            result = asyncio.run(
                whatsapp.handle_event({"chat": "Faraz", "text": "shukriya bhai"})
            )
        assert result.get("replied") is True
        assert fake.sent[-1] == {"chat": "Faraz", "text": "theek, shukriya"}
        out = [m for m in whatsapp.history("Faraz")["messages"] if m["direction"] == "out"]
        assert any(m["text"] == "theek, shukriya" for m in out)

        # auto mode with a broken reply target falls back to a suggestion
        fake.sent.clear()
        fake.fail_reply = "reply target expired - open the chat in WhatsApp again"
        with fake_provider("dobara try karo"):
            result = asyncio.run(
                whatsapp.handle_event({"chat": "Faraz", "text": "ok done"})
            )
        assert result.get("replied") is not True
        assert "expired" in result.get("error", "")
        assert result.get("suggestion") == "dobara try karo"
        assert whatsapp.get_suggestion("Faraz")["text"] == "dobara try karo"

        # generation failure never loses the recording
        fake.fail_reply = None
        whatsapp.dismiss_suggestion("Faraz")
        original = llm.has_provider
        llm.has_provider = lambda: False
        try:
            result = asyncio.run(
                whatsapp.handle_event({"chat": "Faraz", "text": "provider down?"})
            )
        finally:
            llm.has_provider = original
        assert result["stored"] is True and "provider" in result.get("error", "")
        assert whatsapp.get_suggestion("Faraz") is None


# 9
def test_suggestion_accept_and_dismiss():
    with fresh_wa():
        fake = FakeWaBridge()
        whatsapp.set_backend(fake)

        for fn in (whatsapp.accept_suggestion, whatsapp.dismiss_suggestion):
            try:
                fn("Faraz")
                assert False
            except whatsapp.WhatsAppError as exc:
                assert exc.status == 404

        whatsapp.set_suggestion("Faraz", "salam")
        data = whatsapp.accept_suggestion("Faraz")
        assert data["ok"] is True and data["text"] == "salam"
        assert fake.sent == [{"chat": "Faraz", "text": "salam"}]
        assert whatsapp.get_suggestion("Faraz") is None

        # after sending, the suggestion is gone
        try:
            whatsapp.accept_suggestion("Faraz")
            assert False
        except whatsapp.WhatsAppError as exc:
            assert exc.status == 404

        whatsapp.set_suggestion("Ali", "hello")
        assert whatsapp.dismiss_suggestion("Ali")["dismissed"] is True
        assert whatsapp.get_suggestion("Ali") is None


# 10
def test_export_parse_formats_and_directions():
    messages = whatsapp.parse_export(EXPORT_SAMPLE)
    assert len(messages) == 8

    first, second, third = messages[0], messages[1], messages[2]
    assert first == {
        "sender": "Faraz", "direction": "in",
        "text": "salam bhai, kaise ho?", "ts": "2024-03-12 17:04",
    }
    assert second["direction"] == "out" and second["sender"] == "You"
    # continuation line merges into the previous message
    assert third["text"] == "ek kaam tha baat kar sakta hun?"

    media = messages[3]
    assert media["text"] == "<Media omitted>" and media["direction"] == "in"

    system = messages[4]
    assert system["direction"] == "system" and system["sender"] == ""

    # US-style impossible month swaps to month-first (12/31/2024)
    assert messages[5]["ts"] == "2024-12-31 17:04"
    # long dates, both orders, 12h clock converts to 24h
    assert messages[6]["ts"] == "2024-03-14 17:04"
    assert messages[7]["ts"] == "2024-03-15 17:04"

    assert whatsapp._chat_from_filename("WhatsApp Chat with Faraz.txt") == "Faraz"
    assert whatsapp._chat_from_filename("_chat.txt") == "WhatsApp Chat"
    assert whatsapp._chat_from_filename("export.zip") == "export"


# 11
def test_import_export_file_txt_and_zip():
    with fresh_wa() as tmp:
        txt = temp_export(tmp, "WhatsApp Chat with Faraz.txt", EXPORT_SAMPLE)
        result = whatsapp.import_export(str(txt))
        assert result["chat"] == "Faraz"
        assert result["parsed"] == 8 and result["added"] == 8 and result["skipped"] == 0

        # re-importing the same file is a no-op (hash dedupe)
        again = whatsapp.import_export(str(txt))
        assert again["added"] == 0 and again["skipped"] == 8

        chats = whatsapp.chats()
        assert len(chats) == 1
        assert chats[0]["chat"] == "Faraz"
        assert chats[0]["total"] == 8
        # 6 inbound (incl. merged continuation + media), 1 outbound, 1 system
        assert chats[0]["inbound"] == 6 and chats[0]["outbound"] == 1
        assert chats[0]["rule"] == "off"

        # explicit chat name overrides the filename
        other = temp_export(tmp, "_chat.txt", EXPORT_SAMPLE)
        r2 = whatsapp.import_export(str(other), chat="Family Group")
        assert r2["chat"] == "Family Group" and r2["added"] == 8

        # zip archives: first .txt inside wins
        zpath = Path(tmp) / "chats.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("_chat.txt", EXPORT_SAMPLE)
        r3 = whatsapp.import_export(str(zpath))
        assert r3["chat"] == "WhatsApp Chat" and r3["added"] == 8

        # rejected inputs
        for bad in ("", "/etc/passwd", str(Path(tmp) / "missing.txt"), tmp):
            try:
                whatsapp.import_export(str(bad))
                assert False, f"expected rejection of {bad!r}"
            except whatsapp.WhatsAppError:
                pass

        # a file with no recognisable messages
        junk = temp_export(tmp, "junk.txt", "just some text\nno dates here\n")
        try:
            whatsapp.import_export(str(junk))
            assert False
        except whatsapp.WhatsAppError as exc:
            assert "no messages" in str(exc)


# 12
def test_style_profile_detects_language_mix():
    with fresh_wa():
        assert whatsapp.style_profile("nobody")["count"] == 0

        whatsapp.record_message("Zoya", "\u0633\u0644\u0627\u0645 \u0628\u062d\u0627\u0621 \u06a9\u064a\u0633\u0627\u0647\u0648\u0627?")
        whatsapp.record_message("Zoya", "\u0627\u064b \u062a\u06be\u06cc\u06a9 \u0647\u0648\u0646")
        profile = whatsapp.style_profile("Zoya")
        assert profile["count"] == 2
        assert profile["urdu_ratio"] > 0.15
        assert "urdu" in profile["languages"]

        whatsapp.record_message("Bilal", "kya haal hai yaar")
        whatsapp.record_message("Bilal", "acha chal theek hai")
        p2 = whatsapp.style_profile("Bilal")
        assert "roman-urdu" in p2["languages"]
        assert p2["roman_urdu_ratio"] > 0.3

        whatsapp.record_message("Anna", "hello how are you today?")
        p3 = whatsapp.style_profile("Anna")
        assert p3["languages"] == ["english"] or "english" in p3["languages"]


# 13
def test_delete_chat_removes_messages_and_suggestion():
    with fresh_wa():
        whatsapp.record_message("Faraz", "hello")
        whatsapp.record_message("Faraz", "world")
        whatsapp.record_message("Ali", "keep me")
        whatsapp.set_suggestion("Faraz", "draft")

        removed = whatsapp.delete_chat("Faraz")
        assert removed == 2
        assert whatsapp.history("Faraz")["count"] == 0
        assert whatsapp.get_suggestion("Faraz") is None
        assert whatsapp.history("Ali")["count"] == 1

        try:
            whatsapp.delete_chat("  ")
            assert False
        except whatsapp.WhatsAppError:
            pass


# 14
def test_http_endpoints_full_flow():
    with fresh_wa() as tmp:
        c = client()

        r = c.get("/api/whatsapp/status")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] and data["supported"] is False and data["listen"] is True

        # settings: validation errors are 400, saves round-trip
        r = c.post("/api/whatsapp/settings", json={"rules": {"Faraz": "shout"}})
        assert r.status_code == 400 and "mode" in r.json()["error"]
        r = c.post(
            "/api/whatsapp/settings",
            json={"listen": True, "auto_reply": True, "cooldown": 45, "rules": {"Faraz": "auto"}},
        )
        assert r.status_code == 200
        assert r.json()["rules"] == {"Faraz": "auto"} and r.json()["cooldown"] == 45

        # import a real file
        txt = temp_export(tmp, "WhatsApp Chat with Faraz.txt", EXPORT_SAMPLE)
        r = c.post("/api/whatsapp/import", json={"path": str(txt)})
        assert r.status_code == 200
        assert r.json()["added"] == 8 and r.json()["chat"] == "Faraz"

        r = c.get("/api/whatsapp/chats")
        chats = r.json()["chats"]
        assert len(chats) == 1 and chats[0]["total"] == 8 and chats[0]["rule"] == "auto"

        r = c.get("/api/whatsapp/history", params={"chat": "Faraz", "limit": 3})
        assert r.json()["count"] == 3

        # event without a bridge: auto rule degrades to a recorded message + reason
        r = c.post("/api/whatsapp/event", json={"chat": "Faraz", "text": "naya message"})
        assert r.status_code == 200
        body = r.json()
        assert body["stored"] is True
        assert body["reply"]["ok"] is False

        # event requires a chat
        r = c.post("/api/whatsapp/event", json={"chat": "", "text": "x"})
        assert r.status_code == 400

        # generate drafts a suggestion with the fake provider, accept sends via bridge
        fake = FakeWaBridge()
        fake.targets = ["Faraz"]
        whatsapp.set_backend(fake)
        with fake_provider("salam, sab theek"):
            r = c.post("/api/whatsapp/generate", json={"chat": "Faraz"})
        assert r.status_code == 200 and r.json()["text"] == "salam, sab theek"

        r = c.post("/api/whatsapp/suggestion/accept", json={"chat": "Faraz"})
        assert r.status_code == 200
        assert fake.sent[-1]["text"] == "salam, sab theek"

        with fake_provider("aur batao"):
            r = c.post("/api/whatsapp/generate", json={"chat": "Faraz"})
        assert r.status_code == 200
        r = c.post("/api/whatsapp/suggestion/dismiss", json={"chat": "Faraz"})
        assert r.status_code == 200 and r.json()["dismissed"] is True
        r = c.post("/api/whatsapp/suggestion/dismiss", json={"chat": "Faraz"})
        assert r.status_code == 404

        # reply endpoint: bridge error maps to 400, success records the outbound
        fake.fail_reply = "no open reply target for this chat"
        r = c.post("/api/whatsapp/reply", json={"chat": "Faraz", "text": "direct"})
        assert r.status_code == 400 and "reply target" in r.json()["error"]
        fake.fail_reply = None
        r = c.post("/api/whatsapp/reply", json={"chat": "Faraz", "text": "direct"})
        assert r.status_code == 200 and r.json()["ok"] is True

        # delete chat
        r = c.delete("/api/whatsapp/chats/Faraz")
        assert r.status_code == 200 and r.json()["removed"] >= 9
        r = c.get("/api/whatsapp/chats")
        assert r.json()["count"] == 0


# 15
def test_http_status_reflects_bridge():
    with fresh_wa():
        c = client()
        fake = FakeWaBridge()
        fake.targets = ["Ali", "Zoya"]
        whatsapp.set_backend(fake)

        data = c.get("/api/whatsapp/status").json()
        assert data["supported"] is True and data["listener"] is True
        assert data["targets"] == ["Ali", "Zoya"]
        assert "note" not in data

        fake.listener = False
        data = c.get("/api/whatsapp/status").json()
        assert data["listener"] is False


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name} PASSED")
