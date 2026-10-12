"""Client for connecting Jarvis to a running Atif Assistant instance.

Atif Assistant exposes a JSON API (default http://127.0.0.1:8770). Jarvis can
route questions through it so both assistants share the same intelligence and
memory, or fall back to its own LLM/basic modes when Atif is unreachable.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from .config import ATIF_URL


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
