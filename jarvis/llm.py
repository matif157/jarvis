"""Multi-provider LLM support for Jarvis.

Tries providers in order and falls back cleanly. If no provider is
configured, the caller keeps its offline behaviour.

Keys and models can be set in `.env` (read once at launch) or at runtime from
settings (stored in the local database). The database wins when a row is
present - including an empty row, which means "cleared".
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .config import (
    MODEL_DEFAULTS,
    PROVIDER_ENV_KEYS,
    PROVIDER_LABELS,
    PROVIDER_ORDER,
)


class ProviderError(RuntimeError):
    """Raised when no provider is available."""


def _override(name: str, field: str) -> Optional[str]:
    """Return the stored runtime value, or None if it was never set.

    None means "fall back to the environment". An empty string is a real value
    that intentionally blanks the setting.
    """
    try:
        from . import db

        return db.get_setting(f"provider.{name}.{field}", None)
    except Exception:  # noqa: BLE001 - config must never crash a request
        return None


def provider_key(name: str) -> str:
    """The API key for a provider: database override, else environment."""
    override = _override(name, "api_key")
    if override is not None:
        return override
    return os.environ.get(PROVIDER_ENV_KEYS.get(name, ""), "")


def provider_model(name: str) -> str:
    """The model slug for a provider: database override, else default."""
    override = _override(name, "model")
    if override is not None:
        return override
    return MODEL_DEFAULTS.get(name, "")


def provider_enabled(name: str) -> bool:
    """Whether a provider may be used. Defaults to enabled."""
    override = _override(name, "enabled")
    if override is None:
        return True
    return str(override).strip().lower() not in {"0", "false", "off", "no"}


def ollama_url() -> str:
    """The local server URL: database override, else environment, else default."""
    override = _override("ollama", "url")
    if override is not None:
        return override
    return os.environ.get("JARVIS_OLLAMA_URL", "http://127.0.0.1:11434")


def mask_key(key: str) -> str:
    """A safe hint for the UI. Never returns enough to reconstruct the key."""
    if not key:
        return ""
    tail = key[-4:] if len(key) >= 4 else key
    return f"…{tail}"


async def _post_retry(
    client: httpx.AsyncClient, url: str, **kw: Any
) -> httpx.Response:
    """POST with a couple of retries on transient errors."""
    last: Optional[Exception] = None
    for attempt in range(3):
        try:
            r = await client.post(url, **kw)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        except httpx.HTTPStatusError:
            raise
        except Exception as exc:  # noqa: BLE001
            last = exc
            await asyncio.sleep(1.0 * (attempt + 1))
    if last is not None:
        raise last
    raise ProviderError("request failed")


async def _groq(model: str, messages: List[dict], **kw: Any) -> str:
    key = kw.get("key") or provider_key("groq")
    if not key:
        raise ProviderError("no GROQ_API_KEY")
    async with httpx.AsyncClient(timeout=kw.get("timeout", 60)) as client:
        r = await _post_retry(
            client,
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "messages": messages,
                "temperature": kw.get("temperature", 0.4),
                "max_tokens": kw.get("max_tokens", 1800),
            },
        )
        return r.json()["choices"][0]["message"]["content"]


async def _gemini(model: str, messages: List[dict], **kw: Any) -> str:
    key = kw.get("key") or provider_key("gemini")
    if not key:
        raise ProviderError("no GEMINI_API_KEY")
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    turns = [
        {
            "role": "user" if m["role"] == "user" else "model",
            "parts": [{"text": m["content"]}],
        }
        for m in messages
        if m["role"] != "system"
    ]
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    body: Dict[str, Any] = {
        "contents": turns,
        "generationConfig": {
            "temperature": kw.get("temperature", 0.4),
            "maxOutputTokens": kw.get("max_tokens", 1800),
        },
    }
    if system.strip():
        body["systemInstruction"] = {"parts": [{"text": system}]}
    async with httpx.AsyncClient(timeout=kw.get("timeout", 60)) as client:
        r = await _post_retry(client, url, headers={"x-goog-api-key": key}, json=body)
        data = r.json()
        candidates = data.get("candidates") or []
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts)


async def _openrouter(model: str, messages: List[dict], **kw: Any) -> str:
    key = kw.get("key") or provider_key("openrouter")
    if not key:
        raise ProviderError("no OPENROUTER_API_KEY")
    async with httpx.AsyncClient(timeout=kw.get("timeout", 60)) as client:
        r = await _post_retry(
            client,
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "HTTP-Referer": "http://localhost:8771",
            },
            json={
                "model": model,
                "messages": messages,
                "temperature": kw.get("temperature", 0.4),
                "max_tokens": kw.get("max_tokens", 1800),
            },
        )
        return r.json()["choices"][0]["message"]["content"]


async def _ollama(model: str, messages: List[dict], **kw: Any) -> str:
    base = kw.get("url") or ollama_url()
    async with httpx.AsyncClient(timeout=kw.get("timeout", 120)) as client:
        r = await client.post(
            f"{base}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": kw.get("temperature", 0.4)},
            },
        )
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "")


HANDLERS = {
    "groq": _groq,
    "gemini": _gemini,
    "openrouter": _openrouter,
    "ollama": _ollama,
}


async def complete(
    messages: List[dict],
    temperature: float = 0.4,
    max_tokens: int = 1800,
) -> Tuple[str, str]:
    """Return (text, provider_used). Raises if every provider fails."""
    last_error: Optional[Exception] = None

    for name in PROVIDER_ORDER:
        if not provider_enabled(name):
            continue
        handler = HANDLERS.get(name)
        if handler is None:
            continue
        try:
            text = await handler(
                provider_model(name),
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if text and text.strip():
                return text.strip(), name
        except Exception as exc:  # noqa: BLE001 - try the next provider
            last_error = exc
            continue

    raise ProviderError(f"no provider available: {last_error}")


def has_provider() -> bool:
    """Whether any usable provider is configured (cheap, no network).

    A hosted provider counts when it has a key. Ollama is local and has no key
    requirement, so it only counts when the user has explicitly enabled it or
    set a custom URL, otherwise every fresh install would report "available".
    """
    for name in PROVIDER_ORDER:
        if not provider_enabled(name):
            continue
        if name == "ollama":
            if _override("ollama", "enabled") is not None or _override("ollama", "url") is not None:
                return True
            continue
        if provider_key(name):
            return True
    return False


async def ollama_is_up(url: Optional[str] = None) -> bool:
    """Actually probe Ollama. Being configured is not being ready."""
    base = url or ollama_url()
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            r = await client.get(f"{base}/api/tags")
        return r.status_code == 200
    except Exception:
        return False


# Live probe results, cached so a status poll does not spend API quota.
_PROBE_CACHE: Dict[str, Any] = {"at": 0.0, "result": None}
_PROBE_TTL = 120.0


def invalidate_probe_cache() -> None:
    """Drop the cached probe so the next status call reflects a config change."""
    _PROBE_CACHE["at"] = 0.0
    _PROBE_CACHE["result"] = None


def provider_status(name: str) -> Dict[str, Any]:
    """Configuration (not readiness) for one provider, with a masked key."""
    key = provider_key(name)
    configured = name == "ollama" or bool(key)
    out: Dict[str, Any] = {
        "name": name,
        "label": PROVIDER_LABELS.get(name, name),
        "configured": configured,
        "enabled": provider_enabled(name),
        "model": provider_model(name),
        "key_set": bool(key),
        "key_hint": mask_key(key),
        "ready": False,
        "error": None,
    }
    if name == "ollama":
        out["url"] = ollama_url()
    return out


def available_providers() -> List[Dict[str, Any]]:
    """Sync snapshot of provider configuration only."""
    return [provider_status(name) for name in PROVIDER_ORDER]


async def _probe_one(name: str) -> Dict[str, Any]:
    result = await test_provider(name)
    return {"name": name, **result}


async def probe_providers(force: bool = False) -> List[Dict[str, Any]]:
    """Live readiness for every provider, cached for _PROBE_TTL seconds."""
    now = time.time()
    cached = _PROBE_CACHE.get("result")
    if (
        not force
        and cached is not None
        and (now - float(_PROBE_CACHE.get("at", 0.0))) < _PROBE_TTL
    ):
        return cached  # type: ignore[return-value]

    probes = await asyncio.gather(*(_probe_one(n) for n in PROVIDER_ORDER))
    out = [
        {
            "name": name,
            "label": PROVIDER_LABELS.get(name, name),
            "ready": probe["ready"],
            "enabled": provider_enabled(name),
            "note": provider_model(name),
            "error": probe["error"],
        }
        for name, probe in zip(PROVIDER_ORDER, probes)
    ]
    _PROBE_CACHE["at"] = now
    _PROBE_CACHE["result"] = out
    return out


async def test_provider(
    name: str,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    url: Optional[str] = None,
    timeout: float = 8.0,
) -> Dict[str, Any]:
    """Test one provider with optional unsaved overrides."""
    if name not in HANDLERS:
        return {"ready": False, "error": "unknown provider", "provider": name}

    use_model = model or provider_model(name)
    started = time.monotonic()
    try:
        if name == "ollama":
            ok = await ollama_is_up(url or ollama_url())
            return {
                "provider": name,
                "ready": ok,
                "model": use_model,
                "error": None if ok else "not reachable",
                "latency_ms": int((time.monotonic() - started) * 1000),
            }
        if not (api_key or provider_key(name)):
            return {
                "provider": name,
                "ready": False,
                "model": use_model,
                "error": "no key set",
                "latency_ms": 0,
            }
        await HANDLERS[name](
            use_model,
            [{"role": "user", "content": "ping"}],
            temperature=0.0,
            max_tokens=1,
            timeout=timeout,
            key=api_key or None,
            url=url,
        )
        return {
            "provider": name,
            "ready": True,
            "model": use_model,
            "error": None,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }
    except httpx.HTTPStatusError as exc:
        body = ""
        try:
            body = exc.response.json().get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            body = ""
        return {
            "provider": name,
            "ready": False,
            "model": use_model,
            "error": f"HTTP {exc.response.status_code}" + (f": {body[:120]}" if body else ""),
            "latency_ms": int((time.monotonic() - started) * 1000),
        }
    except Exception as exc:  # noqa: BLE001 - any failure means not ready
        return {
            "provider": name,
            "ready": False,
            "model": use_model,
            "error": f"{type(exc).__name__}: {str(exc)[:120]}",
            "latency_ms": int((time.monotonic() - started) * 1000),
        }
