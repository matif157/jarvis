"""Phase 4 memory tests."""


from jarvis import assistant, memory_enhanced


def test_memory_search_filters():
    mem = memory_enhanced.EnhancedMemory()
    mem.remember_fact("location", "home", session="test2")
    mem.remember_fact("other", "x", session="test2")
    res = mem.search("loc", session="test2")
    assert any(r["key"] == "location" for r in res)
    assert all(r["key"] != "other" for r in res)


def test_assistant_injects_memories(monkeypatch):
    a = assistant.Assistant(mode="basic")
    mem = memory_enhanced.EnhancedMemory()
    mem.remember_fact("pref_theme", "dark", session=a.session)
    ctx = a._get_context_memories("theme")
    assert any("dark" in c.get("content", "") for c in ctx)
