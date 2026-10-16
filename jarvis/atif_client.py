"""Client for connecting Jarvis to a running Atif Assistant instance.

Atif Assistant exposes a JSON API (default http://127.0.0.1:8770). Jarvis can
route questions through it so both assistants share the same intelligence and
memory, or fall back to its own LLM/basic modes when Atif is unreachable.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Dict, List, Optional

import httpx

from .config import ATIF_URL
from .tools import Tool, ToolResult


def base_url() -> str:
    """The configured Atif URL: database override, else environment."""
    try:
        from . import db

        override = db.get_setting("atif.url", None)
        if override is not None and override.strip():
            return override.strip()
    except Exception:  # noqa: BLE001
        pass
    return ATIF_URL


async def health(url: Optional[str] = None, timeout: float = 3.0) -> Dict[str, Any]:
    """Check whether Atif Assistant is reachable and what it reports."""
    target = (url or base_url()).rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(f"{target}/api/health")
            r.raise_for_status()
            return {"ok": True, "url": target, "data": r.json()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "url": target, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}


async def ask(
    question: str,
    session: Optional[str] = None,
    url: Optional[str] = None,
    timeout: float = 120.0,
) -> Dict[str, Any]:
    """Send a question to Atif Assistant and return its response dict."""
    target = (url or base_url()).rstrip("/")
    payload: Dict[str, Any] = {"question": question}
    if session:
        payload["session"] = session
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(f"{target}/api/ask", json=payload)
            r.raise_for_status()
            return {"ok": True, "data": r.json()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


# ---------------------------------------------------------------------------
# Synchronous helpers + tools
#
# Tool.run executes synchronously (even from the async action loop), so the
# bridge tools use blocking HTTP rather than the async client above.
# ---------------------------------------------------------------------------
def _sync_request(
    method: str,
    path: str,
    payload: Optional[Dict[str, Any]] = None,
    timeout: float = 8.0,
) -> Dict[str, Any]:
    target = base_url().rstrip("/")
    url = f"{target}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            body = resp.read().decode("utf-8", "replace")
        parsed = json.loads(body) if body.strip() else {}
        return {"ok": True, "url": target, "data": parsed}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "url": target, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def health_sync() -> Dict[str, Any]:
    return _sync_request("GET", "/api/health")


def ask_sync(question: str, session: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"question": question}
    if session:
        payload["session"] = session
    return _sync_request("POST", "/api/ask", payload=payload, timeout=120.0)


class AtifStatusTool(Tool):
    name = "atif.status"
    description = "Report the Atif Assistant bridge URL and reachability"
    permissions = ["atif.read"]

    def run(self) -> ToolResult:
        from . import db

        result = health_sync()
        mode = "unknown"
        try:
            mode = db.get_setting("answer.mode", "auto") or "auto"
        except Exception:  # noqa: BLE001
            pass
        return ToolResult(
            success=True,
            result={
                "url": result["url"],
                "reachable": result["ok"],
                "mode": mode,
                "data": result.get("data"),
                "error": result.get("error"),
            },
            tool=self.name,
            meta={"reachable": result["ok"]},
        )


class AtifAskTool(Tool):
    name = "atif.ask"
    description = "Ask the connected Atif Assistant a question (honest fallback when unreachable)"
    permissions = ["atif.ask"]

    def run(self, question: str = "", session: str = "") -> ToolResult:
        if not question or not question.strip():
            return ToolResult(success=False, error="question is required", tool=self.name)
        result = ask_sync(question.strip(), session=session or None)
        if not result["ok"]:
            return ToolResult(
                success=False,
                error=f"Atif unreachable: {result.get('error')}",
                tool=self.name,
                meta={"url": result["url"]},
            )
        data = result["data"] or {}
        return ToolResult(
            success=True,
            result={"text": data.get("text", ""), "url": result["url"]},
            tool=self.name,
        )


class AtifSetUrlTool(Tool):
    name = "atif.set_url"
    description = "Set the Atif Assistant bridge URL, e.g. http://127.0.0.1:8770"
    permissions = ["atif.config"]

    def run(self, url: str = "") -> ToolResult:
        url = (url or "").strip()
        if not url.startswith(("http://", "https://")):
            return ToolResult(success=False, error="url must start with http:// or https://", tool=self.name)
        from . import db

        db.set_setting("atif.url", url)
        return ToolResult(success=True, result={"url": url}, tool=self.name)


def get_atif_tools() -> List[Tool]:
    """Return all Phase 14 Atif bridge tools."""
    return [AtifStatusTool(), AtifAskTool(), AtifSetUrlTool()]


def get_atif_tools_for_registry() -> List[Tool]:
    return get_atif_tools()
