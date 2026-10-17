"""Basic conversation tests."""

import builtins
import contextlib
import io

from jarvis import assistant, nlu


def test_nlu_time():
    cls = nlu.classify_intent("what time is it")
    assert cls["intent"] == "time"


def test_nlu_find():
    cls = nlu.classify_intent("find my resume")
    assert cls["intent"] == "find"


def test_basic_respond_greet():
    a = assistant.Assistant(mode="basic")
    r = a.basic_respond("hi")
    assert "Jarvis" in r or "Good" in r


def test_start_session_terminates_cleanly():
    a = assistant.Assistant(mode="basic")
    replies = iter(["exit"])
    original_input = builtins.input
    builtins.input = lambda *a, **k: next(replies)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            a.start()
    finally:
        builtins.input = original_input
    out = buf.getvalue()
    assert a.is_active is False
    assert "Goodbye" in out

