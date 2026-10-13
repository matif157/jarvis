"""Multi-step action loop for LLM-driven tool use."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .logging import get_logger
from .tools import ToolRegistry, get_enhanced_registry

logger = get_logger(__name__)


class ActionLoop:
    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        router=None,
        max_steps: int = 4,
        interactive: bool = False,
    ):
        from .router import Router

        self.registry = registry or get_enhanced_registry()
        self.router = router or Router(registry=self.registry)
        self.max_steps = max(1, max_steps)
        self.interactive = interactive

    def _confirm(self, name: str, args: Dict[str, Any], perms: List[str]) -> bool:
        if not self.interactive or not perms:
            return True
        try:
            prompt = f"Run tool '{name}' with perms {perms}? [y/N]: "
            ans = input(prompt).strip().lower()
            return ans in ("y", "yes")
        except Exception:
            return False

    async def run(
        self,
        query: str,
        history: Optional[List[dict]] = None,
        context: Optional[List[dict]] = None,
        provider: Optional[str] = None,
    ) -> Dict[str, Any]:
        history = list(history or [])
        context = list(context or [])
        steps: List[Dict[str, Any]] = []
        current_query = query

        for i in range(self.max_steps):
            decision = await self.router.route(
                current_query,
                history=history[-8:],
                context=context,
                provider=provider,
            )
            if decision.get("kind") == "chat":
                text = str(decision.get("text") or "").strip()
                return {
                    "kind": "chat",
                    "text": text,
                    "provider": decision.get("provider"),
                    "steps": steps,
                }
            if decision.get("kind") == "tool":
                tool = decision.get("tool")
                args = decision.get("args") or {}
                spec = self.registry.get(tool) if tool else None
                perms = []
                if spec:
                    try:
                        perms = list(getattr(spec, "permissions", []) or [])
                    except Exception:
                        perms = []
                if not self._confirm(tool, args, perms):
                    msg = f"Tool {tool} cancelled by user."
                    return {
                        "kind": "chat",
                        "text": msg,
                        "provider": decision.get("provider"),
                        "steps": steps,
                        "cancelled": True,
                    }
                res = self.registry.execute(tool, confirm=False, **args)
                steps.append(
                    {
                        "step": i + 1,
                        "tool": tool,
                        "args": args,
                        "result": res.to_dict(),
                    }
                )
                if not res.success:
                    return {
                        "kind": "chat",
                        "text": f"Tool {tool} failed: {res.error}",
                        "provider": decision.get("provider"),
                        "steps": steps,
                    }
                context.append(
                    {
                        "role": "system",
                        "content": f"Tool {tool} result: {res.result}",
                    }
                )
                current_query = "Continue based on the last tool result. Answer directly or call exactly one tool if needed."
                continue
            return {"kind": "basic", "text": current_query, "steps": steps}

        return {
            "kind": "chat",
            "text": "Reached max steps without final answer.",
            "steps": steps,
        }
