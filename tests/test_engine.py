"""Engine tests."""

from jarvis import engine


def test_engine_process_sync():
    e = engine.Engine(mode="basic")
    res = e.process_sync("hi")
    assert "Jarvis" in res or len(res) > 0
