"""Jarvis Assistant - main conversational interface."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from . import atif_client, db, llm

SYSTEM_PROMPT = (
    "You are Jarvis, a concise, local-first personal assistant. "
    "Answer directly and briefly. Do not add filler or disclaimers. "
    "If you do not know something, say so plainly."
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

    def greet(self) -> str:
        hour = datetime.now().hour
        if 5 <= hour < 12:
            return f"Good morning! I'm {self.name}, your personal assistant."
        elif 12 <= hour < 18:
            return f"Good afternoon! I'm {self.name}, your personal assistant."
        else:
            return f"Good evening! I'm {self.name}, your personal assistant."

    # ------------------------------------------------------- basic offline
    def basic_respond(self, query: str) -> str:
        query_lower = query.lower()
        if "hello" in query_lower or "hi" in query_lower or "hey" in query_lower:
            return self.greet()
        elif "time" in query_lower:
            return f"The current time is {datetime.now().strftime('%I:%M %p')}"
        elif "date" in query_lower:
            return f"Today is {datetime.now().strftime('%A, %B %d, %Y')}"
        elif "help" in query_lower or "what can you do" in query_lower or "capabilities" in query_lower:
            return (
                "I can save notes, track tasks, remember things, tell the time and "
                "date, and answer questions. Add an API key in settings to enable "
                "AI answers, or connect me to Atif Assistant."
            )
        elif "note" in query_lower:
            return "To save a note: 'python3 main.py note'"
        elif "task" in query_lower or "todo" in query_lower:
            return "To create a task: 'python3 main.py task'"
        elif "weather" in query_lower:
            from .weather import Weather

            info = Weather().get_weather()
            return f"Weather in {info['location']}: {info['temperature']}°C, {info['condition']}"
        elif "remember" in query_lower:
            return "I can remember things - use the memory system to store key information."
        else:
            return f"I understand you said: '{query}'. How can I help you further?"

    # --------------------------------------------------------- LLM answer
    async def llm_respond(self, query: str) -> tuple:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(self.history[-6:])
        messages.append({"role": "user", "content": query})
        try:
            text, provider = await llm.complete(messages)
            return text, provider
        except Exception as exc:  # noqa: BLE001
            return None, f"error: {exc}"

    # -------------------------------------------------------- Atif answer
    async def atif_respond(self, query: str) -> tuple:
        result = await atif_client.ask(query, session=self.session)
        if result.get("ok"):
            return result["data"].get("text", ""), "atif"
        return None, result.get("error", "atif unreachable")

    # --------------------------------------------------------- dispatcher
    async def answer(self, query: str) -> str:
        """Answer a query using the configured mode with graceful fallback."""
        if self.mode in ("auto", "atif"):
            res = await self.atif_respond(query)
            if res[0]:
                self._record(query, res[0])
                return f"{res[0]}\n\n[via Atif Assistant]"
            if self.mode == "atif":
                return f"Atif Assistant is unavailable ({res[1]})."

        if self.mode in ("auto", "llm") and llm.has_provider():
            res = await self.llm_respond(query)
            if res[0]:
                self._record(query, res[0])
                return f"{res[0]}\n\n[via {res[1]}]"
            if self.mode == "llm":
                return f"AI answer failed ({res[1]}); falling back to basics.\n\n{self.basic_respond(query)}"

        text = self.basic_respond(query)
        self._record(query, text)
        return text

    def _record(self, query: str, answer: str) -> None:
        self.history.append({"role": "user", "content": query})
        self.history.append({"role": "assistant", "content": answer})
        try:
            db.save_message(self.session, "user", query)
            db.save_message(self.session, "assistant", answer)
        except Exception:  # noqa: BLE001
            pass

    def start(self) -> None:
        self.is_active = True
        print(self.greet())
        print(f"Mode: {self.mode}. Type 'exit' to quit, 'help' for assistance.\n")

        while self.is_active:
            try:
                user_input = input("> ").strip()
                if not user_input:
                    continue
                if user_input.lower() in ("exit", "quit", "bye", "q"):
                    print("Goodbye! Have a great day!")
                    self.is_active = False
                    break
                response = asyncio.run(self.answer(user_input))
                print(response)
            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye!")
                self.is_active = False
                break
