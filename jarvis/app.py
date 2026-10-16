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
from pydantic import BaseModel, Field

from . import db, llm
from . import __version__
from .config import HOST, PORT, PROVIDER_LABELS, PROVIDER_ORDER, get_web_dir
from .tools import get_enhanced_registry

app = FastAPI(title="Jarvis", version=__version__)


class Ask(BaseModel):
    question: str
    session: Optional[str] = None
    mode: Optional[str] = None


class ChatIn(BaseModel):
    message: str
    session: Optional[str] = None
    mode: Optional[str] = None


class ToolExec(BaseModel):
    params: dict = Field(default_factory=dict)
    confirm: bool = False


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
async def health(probe: bool = True) -> dict:
    providers = await llm.probe_providers() if probe else []
    return {
        "ok": True,
        "app": "jarvis",
        "providers": providers,
        "has_provider": llm.has_provider(),
    }


@app.get("/api/status")
def status() -> dict:
    """Server snapshot: tool count and subsystem availability (no network)."""
    try:
        tools = get_enhanced_registry().list_tools()
        tool_count = len(tools)
    except Exception:
        tool_count = 0
    try:
        from .voice import VoiceManager

        voice = VoiceManager().status()
    except Exception:
        voice = {"tts": {"available": False}, "stt": {"available": False}}
    return {
        "ok": True,
        "app": "jarvis",
        "version": app.version,
        "tools": tool_count,
        "has_provider": llm.has_provider(),
        "voice": voice,
        "host": HOST,
        "port": PORT,
    }


@app.get("/api/tools")
def list_tools() -> dict:
    """List every registered tool with its description and permissions."""
    tools = get_enhanced_registry().list_tools()
    return {"count": len(tools), "tools": tools}


@app.post("/api/tools/{name}")
def run_tool(name: str, payload: ToolExec = ToolExec()) -> JSONResponse:
    """Execute a registered tool by name.

    Confirmation-gated permissions (e.g. ``email.send``, ``voice.listen``)
    require ``confirm: true`` in the body; otherwise the tool reports that
    confirmation is required instead of running.
    """
    registry = get_enhanced_registry()
    if registry.get(name) is None:
        return JSONResponse(
            {"success": False, "error": f"unknown tool: {name}", "tool": name},
            status_code=404,
        )
    result = registry.execute(name, confirm=payload.confirm, **(payload.params or {}))
    return JSONResponse(result.to_dict())


@app.post("/api/chat")
async def chat(payload: ChatIn) -> dict:
    """Chat with the assistant, returning which provider/tool answered."""
    from .assistant import Assistant

    assistant = Assistant(mode=payload.mode or "auto")
    if payload.session:
        assistant.session = payload.session
    text, provider, tool = await assistant.respond(payload.message)
    return {
        "text": text,
        "provider": provider,
        "tool": tool,
        "session": assistant.session,
        "mode": assistant.mode,
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
