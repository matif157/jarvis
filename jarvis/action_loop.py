"""Multi-step action loop for LLM-driven tool use.

The router only *decides* (chat vs. tool + args); this loop is the single place
that executes tools. That guarantees each chosen tool runs exactly once and
lets confirmation-gated tools be approved (interactive) or safely declined
(non-interactive) here.
"""

from __future__ import annotations

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

    def _perms_for(self, tool: Optional[str]) -> List[str]:
        spec = self.registry.get(tool) if tool else None
        if not spec:
            return []
        try:
            return list(getattr(spec, "permissions", []) or [])
        except Exception:
            return []

    def _ask_user(self, tool: str, perms: List[str]) -> bool:
        try:
            prompt = f"Run tool '{tool}' with perms {perms}? [y/N]: "
            return input(prompt).strip().lower() in ("y", "yes")
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
                perms = self._perms_for(tool)
                confirm = True
                if any(self.registry.perms.needs_confirmation(p) for p in perms):
                    if self.interactive:
                        if not self._ask_user(tool, perms):
                            return {
                                "kind": "chat",
                                "text": f"Tool {tool} cancelled by user.",
                                "provider": decision.get("provider"),
                                "steps": steps,
                                "cancelled": True,
                            }
                    else:
                        # Let the registry surface a needs_confirmation result honestly.
                        confirm = False

                res = self.registry.execute(tool, confirm=confirm, **args)
                steps.append(
                    {
                        "step": len(steps) + 1,
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
