"""Question routing for Jarvis."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from . import llm
from .logging import get_logger
from .tools import ToolRegistry, get_enhanced_registry

logger = get_logger(__name__)

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

ROUTING_SYSTEM_PROMPT = (
    "You are Jarvis, a local-first personal assistant. Decide whether to "
    "answer directly or call exactly one tool.\n"
    "Available tools:\n{tools}\n"
    "Reply with a single JSON object and nothing else.\n"
    'To call a tool: {{"tool": "<name>", "args": {{...}}}}\n'
    'To answer directly: {{"tool": null, "reply": "<short answer>"}}'
)


def tool_catalog(registry: ToolRegistry) -> str:
    lines: List[str] = []
    for spec in registry.list_tools():
        perms = ", ".join(spec.get("permissions") or [])
        suffix = f" (permissions: {perms})" if perms else ""
        lines.append(f"- {spec['name']}: {spec['description']}{suffix}")
    return "\n".join(lines) or "- (none)"


def parse_decision(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    cleaned = text.strip()
    # remove fences
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    # try first brace match
    match = _JSON_OBJECT.search(cleaned)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    # try to fix common trailing brace issues
    for cand in (cleaned, cleaned.rstrip('}'), cleaned + '}'):
        try:
            data = json.loads(cand)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return None


class Router:
    def __init__(self, registry: Optional[ToolRegistry] = None, llm_module=llm):
        self.registry = registry or get_enhanced_registry()
        self.llm = llm_module

    def _messages(self, query: str, history: Optional[List[dict]] = None, context: Optional[List[dict]] = None) -> List[dict]:
        system = ROUTING_SYSTEM_PROMPT.format(tools=tool_catalog(self.registry))
        messages: List[dict] = [{"role": "system", "content": system}]
        messages.extend(context or [])
        messages.extend(history or [])
        messages.append({"role": "user", "content": query})
        return messages

    async def route(self, query: str, history: Optional[List[dict]] = None, context: Optional[List[dict]] = None, provider: Optional[str] = None) -> Dict[str, Any]:
        active = provider or await self.llm.active_provider()
        if not active:
            return {"kind": "basic", "provider": None}
        messages = self._messages(query, history=history, context=context)
        try:
            text, used = await self.llm.complete(messages, temperature=0.0)
        except Exception as exc:
            logger.warning("router LLM call failed: %s", exc)
            return {"kind": "basic", "provider": None, "error": str(exc)}
        decision = parse_decision(text)
        if decision and decision.get("tool"):
            name = str(decision.get("tool"))
            args = decision.get("args") or {}
            if not isinstance(args, dict):
                args = {}
            if self.registry.get(name) is None:
                logger.info("router picked unknown tool: %s", name)
                return {"kind": "chat", "text": f"I don't have a tool called '{name}'.", "provider": used}
            # Decide only. The ActionLoop is responsible for executing tools
            # exactly once (and for confirmation gating).
            return {"kind": "tool", "tool": name, "args": args, "text": "", "provider": used}
        reply = (decision or {}).get("reply") if decision else None
        if not reply:
            # if LLM just returned text, use it as-is
            reply = text
        # strip trailing/extra braces if any oddity
        reply = str(reply).strip()
        return {"kind": "chat", "text": reply, "provider": used}
