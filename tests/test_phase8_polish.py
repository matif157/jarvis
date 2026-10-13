"""Phase 8 polish tests."""

from jarvis import engine
import asyncio


def test_engine_answer():
    e = engine.Engine(mode="basic")
    res = asyncio.run(e.answer("hi"))
    assert len(res) > 0


def test_engine_modes():
    e1 = engine.Engine(mode="llm")
    e2 = engine.Engine(mode="auto")
    e3 = engine.Engine(mode="basic")
    assert e1.assistant.mode == "llm"
    assert e2.assistant.mode == "auto"
    assert e3.assistant.mode == "basic"
