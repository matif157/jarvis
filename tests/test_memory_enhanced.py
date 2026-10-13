"""Enhanced memory tests."""

from jarvis import memory_enhanced


def test_remember_fact():
    mem = memory_enhanced.EnhancedMemory()
    mem.remember_fact("test_key", "test_value", session="test")
    facts = mem.get_facts(session="test", limit=10)
    assert any(f["key"] == "test_key" for f in facts)


def test_summarize_short():
    mem = memory_enhanced.EnhancedMemory()
    hist = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    s = mem.summarize_conversation(hist)
    assert s is None or isinstance(s, str)


def test_summarize_long():
    mem = memory_enhanced.EnhancedMemory()
    hist = [{"role": "user", "content": f"msg {i}"} for i in range(10)]
    s = mem.summarize_conversation(hist)
    assert isinstance(s, str)
