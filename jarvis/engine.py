"""Engine for unified routing and orchestration."""

from __future__ import annotations

from typing import Optional

from .assistant import Assistant
from .logging import get_logger

logger = get_logger(__name__)


class Engine:
    def __init__(self, mode: str = "auto"):
        self.assistant = Assistant(mode=mode)
        self.logger = logger

    async def process(self, input_text: str) -> str:
        return await self.assistant.answer_with_tools(input_text)

    def process_sync(self, input_text: str) -> str:
        import asyncio

        return asyncio.run(self.process(input_text))
