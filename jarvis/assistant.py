"""Jarvis Assistant - main conversational interface."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from . import atif_client, db, llm
from .tools import get_default_registry

SYSTEM_PROMPT = (
    "You are Jarvis, a concise, local-first personal assistant. "
    "Answer directly and briefly. Do not add filler or disclaimers. "
    "If you do not know something, say so plainly. "
    "Use tools when they help (available: time.now, echo). "
    "Keep responses short."
)


class Assistant:
    """Main Jarvis assistant class with basic, LLM and Atif modes."""

    def __init__(self, mode: str = "auto"):
        self.name = "Jarvis"
        self.created_at = datetime.now()
        self.is_active = False
        self.mode = mode  # auto | basic | llm | atif
        self.session = f"cli-{int(datetime.now().timestamp())}"
        self.history: list = []
        from .tools import get_enhanced_registry
        self.registry = get_enhanced_registry()

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
        result = await atif_client.ask(query, session=self.session)
        if result.get("ok"):
            return result["data"].get("text", ""), "atif"
        return None, result.get("error", "atif unreachable")

    async def answer(self, query: str) -> str:
        if self.mode in ("auto", "atif"):
            res = await self.atif_respond(query)
            if res[0]:
                self._record(query, res[0])
                return res[0]
            if self.mode == "atif":
                return f"Atif unreachable ({res[1]}). Falling back...\n\n{self.basic_respond(query)}"

        if self.mode in ("auto", "llm") and llm.has_provider():
            res = await self.llm_respond(query)
            if res[0]:
                self._record(query, res[0])
                return res[0]
            if self.mode == "llm":
                return f"AI failed ({res[1]}).\n\n{self.basic_respond(query)}"

        text = self.basic_respond_enhanced(query)
        self._record(query, text)
        return text

    def _record(self, query: str, answer: str) -> None:
        self.history.append({"role": "user", "content": query})
        self.history.append({"role": "assistant", "content": answer})
        try:
            db.save_message(self.session, "user", query)
            db.save_message(self.session, "assistant", answer)
        except Exception:
            pass

    def start(self) -> None:
        self.is_active = True
        print(self.greet())
        print(f"Mode: {self.mode}. Type 'exit' to quit.\n")

        while self.is_active:
            try:
                user_input = input("> ").strip()
                if not user_input:
                    continue
                if user_input.lower() in ("exit", "quit", "bye", "q"):
                    print("Goodbye!")
                    self.is_active = False
                    break
                response = asyncio.run(self.answer(user_input))
                print(response)
            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye!")
                self.is_active = False
                break

    def basic_respond_enhanced(self, query: str) -> str:
        from . import nlu

        cls = nlu.classify_intent(query)
        intent = cls.get("intent")
        if intent == "time":
            return f"The current time is {datetime.now().strftime('%I:%M %p')}"
        if intent == "date":
            return f"Today is {datetime.now().strftime('%A, %B %d, %Y')}"
        if intent == "greet":
            return self.greet()
        if intent == "help":
            return "I can help with notes, tasks, time/date, weather, and more. Describe what you want - I'll figure it out."
        if intent == "note":
            return "To save a note: 'python3 main.py note'"
        if intent == "task":
            return "To create a task: 'python3 main.py task'"
        if intent == "weather":
            from .weather import Weather

            info = Weather().get_weather()
            return f"Weather: {info['temperature']}°C, {info['condition']}"
        if intent == "find":
            return "I can help find files - I'll search authorized locations."
        return self.basic_respond(query)

    async def answer_with_tools(self, query: str) -> str:
        """Simple tool selection based on intent."""
        from . import nlu

        cls = nlu.classify_intent(query)
        intent = cls.get("intent")
        if intent == "time":
            res = self.registry.execute("time.now", confirm=False)
            if res.success:
                return f"Current time: {res.result}"
        if intent == "find":
            # list common dirs
            res = self.registry.execute("fs.list", confirm=False, directory="~/Downloads")
            if res.success and res.result:
                return f"Found in Downloads (first few): {[x['name'] for x in res.result[:5]]}"
        return await self.answer(query)

    def start(self) -> None:
        self.is_active = True
        print(self.greet())
        print(f"Mode: {self.mode}. Type 'exit' to quit.\n")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        while self.is_active:
            try:
                user_input = input("> ").strip()
                if not user_input:
                    continue
                if user_input.lower() in ("exit", "quit", "bye", "q"):
                    print("Goodbye!")
                    self.is_active = False
                    break
                response = loop.run_until_complete(self.answer_with_tools(user_input))
                print(response)
            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye!")
                self.is_active = False
                break

    def _get_context_memories(self, query: str) -> list:
        try:
            from . import memory_enhanced

            mem = memory_enhanced.EnhancedMemory()
            facts = mem.search(query, limit=3)
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
