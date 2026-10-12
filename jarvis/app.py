"""Jarvis web API and settings UI.

Serves a JSON API plus a lightweight settings page for managing AI providers
and API keys. Local-only bind by default.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, llm
from .config import PROVIDER_LABELS, PROVIDER_ORDER, get_web_dir

app = FastAPI(title="Jarvis", version="0.1.0")


class Ask(BaseModel):
    question: str
    session: Optional[str] = None
    mode: Optional[str] = None


class ProviderIn(BaseModel):
    api_key: Optional[str] = None
    model: Optional[str] = None
    url: Optional[str] = None
    clear_key: bool = False
    enabled: Optional[bool] = None


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


@app.get("/api/health")
async def health() -> dict:
    providers = await llm.probe_providers()
    return {
        "ok": True,
        "app": "jarvis",
        "providers": providers,
        "has_provider": llm.has_provider(),
    }


@app.post("/api/ask")
async def ask(payload: Ask) -> dict:
    from .assistant import Assistant

    assistant = Assistant(mode=payload.mode or "auto")
    if payload.session:
        assistant.session = payload.session
    text = await assistant.answer(payload.question)
    return {"text": text, "session": assistant.session}


@app.get("/api/settings")
def get_settings() -> dict:
    conn = db.connect()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    # Provider keys are never returned here.
    return {
        r["key"]: r["value"]
        for r in rows
        if not r["key"].startswith("provider.")
    }


@app.post("/api/settings")
def set_settings(payload: dict) -> dict:
    for k, v in payload.items():
        if v is None or str(k).startswith("provider."):
            continue
        db.set_setting(str(k), str(v))
    return {"ok": True}


@app.get("/api/providers")
async def list_providers(probe: bool = False) -> dict:
    """Provider config with masked keys, plus a live readiness flag."""
    live = {p["name"]: p for p in await llm.probe_providers(force=probe)}
    providers = []
    for name in PROVIDER_ORDER:
        status = llm.provider_status(name)
        status["ready"] = live.get(name, {}).get("ready", False)
        status["error"] = live.get(name, {}).get("error")
        providers.append(status)
    return {"providers": providers, "order": PROVIDER_ORDER}


@app.post("/api/providers/test")
async def test_all_providers() -> dict:
    import asyncio

    results = await asyncio.gather(*(llm.test_provider(n) for n in PROVIDER_ORDER))
    return {"results": results}


@app.post("/api/providers/{name}")
def save_provider(name: str, payload: ProviderIn) -> JSONResponse:
    """Store a provider's key/model/url, or clear its key."""
    if name not in PROVIDER_LABELS:
        return JSONResponse({"error": "unknown provider"}, status_code=404)

    def put_or_clear(key: str, value: Optional[str]) -> None:
        if value is None:
            return
        if value.strip():
            db.set_setting(key, value.strip())
        else:
            db.delete_setting(key)

    if name == "ollama":
        put_or_clear("provider.ollama.url", payload.url)
        put_or_clear("provider.ollama.model", payload.model)
        if payload.clear_key:
            db.set_setting("provider.ollama.api_key", "")
        elif payload.api_key and payload.api_key.strip():
            db.set_setting("provider.ollama.api_key", payload.api_key.strip())
    else:
        if payload.clear_key:
            db.set_setting(f"provider.{name}.api_key", "")
        elif payload.api_key and payload.api_key.strip():
            db.set_setting(f"provider.{name}.api_key", payload.api_key.strip())
        put_or_clear(f"provider.{name}.model", payload.model)
    if payload.enabled is not None:
        db.set_setting(f"provider.{name}.enabled", "1" if payload.enabled else "0")
    llm.invalidate_probe_cache()
    return JSONResponse({"ok": True, "provider": llm.provider_status(name)})


@app.post("/api/providers/{name}/test")
async def test_one_provider(name: str, payload: ProviderIn) -> JSONResponse:
    if name not in PROVIDER_LABELS:
        return JSONResponse({"error": "unknown provider"}, status_code=404)
    result = await llm.test_provider(
        name,
        api_key=payload.api_key,
        model=payload.model,
        url=payload.url,
    )
    return JSONResponse(result)


WEB_DIR = Path(get_web_dir())
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(WEB_DIR / "index.html"))
