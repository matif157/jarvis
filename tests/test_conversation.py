"""Basic conversation tests."""

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
