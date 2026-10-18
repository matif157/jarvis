"""Jarvis Assistant - main conversational interface."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from . import atif_client, db, events, llm
from .action_loop import ActionLoop
from .router import Router

SYSTEM_PROMPT = (
    "You are Jarvis, a concise, local-first personal assistant. "
    "Answer directly and briefly. Do not add filler or disclaimers. "
    "If you do not know something, say so plainly. "
    "You can call tools (the router lists what is available); use them when they help. "
    "Keep responses short."
)


class Assistant:
    """Main Jarvis assistant class with basic, LLM and Atif modes."""

    def __init__(self, mode: str = "auto", interactive: bool = False):
        self.name = "Jarvis"
        self.created_at = datetime.now()
        self.is_active = False
        self.mode = mode  # auto | basic | llm | atif
        self.interactive = interactive
        self.session = f"cli-{int(datetime.now().timestamp())}"
        self.history: list = []
        from .tools import get_enhanced_registry
        self.registry = get_enhanced_registry()
        self.router = Router(registry=self.registry)
        self.action_loop = ActionLoop(registry=self.registry, router=self.router, interactive=interactive)

    def greet(self) -> str:
        hour = datetime.now().hour
        if 5 <= hour < 12:
            return f"Good morning! I'm {self.name}, your personal assistant."
        elif 12 <= hour < 18:
            return f"Good afternoon! I'm {self.name}, your personal assistant."
        else:
            return f"Good evening! I'm {self.name}, your personal assistant."

    def basic_respond(self, query: str) -> str:
        q = query.lower()
        if any(x in q for x in ("hello", "hi", "hey")):
            return self.greet()
        if "time" in q:
            return f"The current time is {datetime.now().strftime('%I:%M %p')}"
        if "date" in q:
            return f"Today is {datetime.now().strftime('%A, %B %d, %Y')}"
        if any(x in q for x in ("help", "what can you do", "capabilities")):
            return (
                "I can save notes, track tasks, remember things, tell time/date, "
                "and answer in natural language. Add API keys for smarter AI."
            )
        if "note" in q:
            return "To save a note: 'python3 main.py note'"
        if any(x in q for x in ("task", "todo")):
            return "To create a task: 'python3 main.py task'"
        if "weather" in q:
            from .weather import Weather

            info = Weather().get_weather()
            return f"Weather in {info['location']}: {info['temperature']}°C, {info['condition']}"
        if "remember" in q:
            return "I can remember things - use the memory system."
        return f"I understand you said: '{query}'. How can I help you further?"

    async def llm_respond(self, query: str) -> tuple:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        # add relevant memories
        messages.extend(self._get_context_memories(query))
        # include last few turns
        for h in self.history[-8:]:
            messages.append(h)
        messages.append({"role": "user", "content": query})
        try:
            text, provider = await llm.complete(messages)
            return text, provider
        except Exception as exc:
            return None, f"error: {exc}"

    async def atif_respond(self, query: str) -> tuple:
        """Ask Atif. Returns (text, error): text is None when Atif cannot answer.

        Atif answering with its own "no provider" fallback counts as not
        answering - the user would otherwise see Atif's canned text as if it
        were Jarvis's diagnosis.
        """
        result = await atif_client.ask(query, session=self.session)
        if not result.get("ok"):
            return None, result.get("error", "atif unreachable")
        data = result.get("data") or {}
        if str(data.get("provider") or "").lower() == "offline":
            return None, "Atif has no model provider configured"
        return str(data.get("text") or ""), None

    async def answer(self, query: str) -> str:
        text, _provider, _tool = await self.respond(query)
        return text

    async def respond(self, query: str, on_event: Optional[events.EventHandler] = None) -> tuple:
        """Route a query and return (text, provider, tool).

        When ``on_event`` is supplied, a structured timeline of what the
        assistant is doing (start, tool calls, results, final message) is
        streamed to it. Behaviour is otherwise unchanged.
        """
        emitter = events.EventEmitter(on_event)

        async def _finish(text: str, provider: str, tool: Optional[str]) -> tuple:
            self._record(query, text)
            await emitter.emit(
                events.EVT_MESSAGE, text=text, provider=provider, tool=tool
            )
            return text, provider, tool

        await emitter.emit(
            events.EVT_START, query=query, session=self.session, mode=self.mode
        )

        try:
            if self.mode == "auto":
                # Local-first: try LLM/router before Atif
                ctx = self._get_context_memories(query)
                loop_res = await self.action_loop.run(
                    query,
                    history=self.history[-8:],
                    context=ctx,
                    on_event=on_event,
                )
                if loop_res.get("kind") == "chat" and loop_res.get("text"):
                    text = loop_res["text"]
                    tool = loop_res.get("steps")[-1]["tool"] if loop_res.get("steps") else None
                    return await _finish(text, loop_res.get("provider") or "llm", tool)
                text, atif_err = await self.atif_respond(query)
                if text:
                    return await _finish(text, "atif", None)
                msg = llm.chat_unavailable_message(atif_err)
                return await _finish(
                    f"{msg}\n\n{self.basic_respond(query)}", "basic", None
                )

            if self.mode == "atif":
                text, atif_err = await self.atif_respond(query)
                if text:
                    return await _finish(text, "atif", None)
                msg = llm.chat_unavailable_message(atif_err)
                return await _finish(
                    f"{msg}\n\n{self.basic_respond(query)}", "basic", None
                )

            if self.mode in ("auto", "llm"):
                ctx = self._get_context_memories(query)
                loop_res = await self.action_loop.run(
                    query,
                    history=self.history[-8:],
                    context=ctx,
                    on_event=on_event,
                )
                if loop_res.get("kind") == "chat" and loop_res.get("text"):
                    text = loop_res["text"]
                    tool = loop_res.get("steps")[-1]["tool"] if loop_res.get("steps") else None
                    return await _finish(text, loop_res.get("provider") or "llm", tool)
                if self.mode == "llm":
                    text = f"AI failed.\n\n{self.basic_respond(query)}"
                    return await _finish(text, "basic", None)

            text = self.basic_respond(query)
            return await _finish(text, "basic", None)
        except Exception as exc:  # noqa: BLE001 - surface failures to the timeline
            await emitter.emit(events.EVT_ERROR, error=str(exc))
            raise

    def _record(self, query: str, answer: str) -> None:
        self.history.append({"role": "user", "content": query})
        self.history.append({"role": "assistant", "content": answer})
        try:
            db.save_message(self.session, "user", query)
            db.save_message(self.session, "assistant", answer)
        except Exception:
            pass
        # Optional: passively capture durable facts the user states (Phase 21).
        try:
            from . import memory_ingest

            memory_ingest.auto_ingest_turn(query, session=self.session)
        except Exception:
            pass

    async def answer_with_tools(self, query: str) -> str:
        """Route a query: LLM router first, NLU shortcuts only in basic mode."""
        if self.mode in ("auto", "llm"):
            text, _provider, _tool = await self.respond(query)
            return text

        from . import nlu

        cls = nlu.classify_intent(query)
        intent = cls.get("intent")
        if intent == "time":
            res = self.registry.execute("time.now", confirm=False)
            if res.success:
                return f"Current time: {res.result}"
        if intent == "find":
            res = self.registry.execute("fs.list", confirm=False, directory="~/Downloads")
            if res.success and res.result:
                return f"Found in Downloads (first few): {[x['name'] for x in res.result[:5]]}"
        return await self.answer(query)

    def start(self) -> None:
        self.is_active = True
        print(self.greet())
        print(f"Mode: {self.mode}. Type 'exit' to quit.\n")
        try:
            asyncio.run(self._chat_session())
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            self.is_active = False

    async def _chat_session(self) -> None:
        while self.is_active:
            try:
                user_input = input("> ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye!")
                self.is_active = False
                break
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "bye", "q"):
                print("Goodbye!")
                self.is_active = False
                break
            response = await self.answer_with_tools(user_input)
            print(response)

    def _get_context_memories(self, query: str) -> list:
        try:
            from . import memory_enhanced

            mem = memory_enhanced.EnhancedMemory()
            facts = mem.search(query, session=self.session, limit=3)
            ctx = []
            for f in facts:
                ctx.append(
                    {
                        "role": "system",
                        "content": f"Memory: {f.get('key')} = {f.get('value')}",
                    }
                )
            return ctx
        except Exception:
            return []
