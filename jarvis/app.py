"""Jarvis web API and settings UI.

Serves a JSON API plus a lightweight settings page for managing AI providers
and API keys. Local-only bind by default.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import (
    __version__,
    db,
    device_control,
    engines,
    llm,
    memory_ingest,
    ondevice,
    service_keys,
    voice,
    whatsapp,
)
from .config import HOST, PORT, PROVIDER_LABELS, PROVIDER_ORDER, get_web_dir
from .tools import get_enhanced_registry

app = FastAPI(title="Jarvis", version=__version__)

# Prefixes whose values are never accepted by (or returned from) /api/settings:
# provider.* -> handled by /api/providers, secret.* -> /api/keys,
# engine.* -> /api/engines (validated there).
_HIDDEN_PREFIXES = ("provider.", "secret.", "engine.")


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


class ServiceKeyIn(BaseModel):
    api_key: Optional[str] = None
    clear_key: bool = False


class EnginesIn(BaseModel):
    llm: Optional[str] = None
    stt: Optional[str] = None
    image: Optional[str] = None


class OnDeviceIn(BaseModel):
    id: Optional[str] = None
    prompt: Optional[str] = None
    max_tokens: Optional[int] = None


class VoiceIn(BaseModel):
    text: str = ""
    voice: str = ""
    rate: float = 0.0
    language: str = ""
    audio_path: str = ""
    seconds: int = 8


class WakeIn(BaseModel):
    keyword: str = "jarvis"


class MemoryIn(BaseModel):
    text: str
    key: Optional[str] = ""
    kind: Optional[str] = "fact"
    source: Optional[str] = ""
    tags: Optional[str] = ""
    session: Optional[str] = ""


class MemoryIngestIn(BaseModel):
    text: str
    source: Optional[str] = ""
    tags: Optional[str] = ""
    mode: Optional[str] = "heuristic"
    session: Optional[str] = ""


class MemoryImportIn(BaseModel):
    path: Optional[str] = None
    items: Optional[list] = None
    source: Optional[str] = None
    legacy: Optional[bool] = False


class MemorySourceIn(BaseModel):
    source: str


class WhatsAppEventIn(BaseModel):
    chat: str
    text: str
    package: Optional[str] = ""
    can_reply: Optional[bool] = False
    ts_ms: Optional[int] = None
    ts: Optional[str] = None
    sender: Optional[str] = ""


class WhatsAppReplyIn(BaseModel):
    chat: str
    text: str


class WhatsAppChatIn(BaseModel):
    chat: str


class WhatsAppSettingsIn(BaseModel):
    listen: Optional[bool] = None
    auto_reply: Optional[bool] = None
    rules: Optional[Dict[str, str]] = None
    cooldown: Optional[int] = None


class WhatsAppImportIn(BaseModel):
    path: str
    chat: Optional[str] = None


class DeviceSettingsIn(BaseModel):
    enabled: Optional[bool] = None


class DeviceActionIn(BaseModel):
    action: str
    x: Optional[int] = None
    y: Optional[int] = None
    index: Optional[int] = None
    direction: Optional[str] = None
    text: Optional[str] = None
    max_chars: Optional[int] = None
    max_nodes: Optional[int] = None


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


def _sse(event: Dict[str, Any]) -> str:
    """Format an event dict as a single Server-Sent Events frame."""
    return f"data: {json.dumps(event, default=str)}\n\n"


@app.get("/api/agent/stream")
async def agent_stream(message: str, session: Optional[str] = None, mode: str = "auto") -> StreamingResponse:
    """Stream the assistant's agent timeline as Server-Sent Events.

    Emits ``start``, ``thought``, ``confirmation``, ``tool_call``,
    ``tool_result``, ``message``, ``error`` and a terminating ``done`` event.
    Uses ``EventSource``-compatible GET so it works in plain browsers and the
    Android WebView without extra dependencies.
    """
    from .assistant import Assistant

    queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()

    async def _handler(event: Dict[str, Any]) -> None:
        await queue.put(event)

    async def _produce() -> None:
        assistant = Assistant(mode=mode or "auto")
        if session:
            assistant.session = session
        try:
            await assistant.respond(message, on_event=_handler)
        except Exception as exc:  # noqa: BLE001 - report on the timeline
            await queue.put({"type": "error", "error": str(exc)})
        finally:
            await queue.put({"type": "done"})

    async def _stream():
        task = asyncio.create_task(_produce())
        try:
            while True:
                event = await queue.get()
                yield _sse(event)
                if event.get("type") == "done":
                    break
        finally:
            if not task.done():
                task.cancel()

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(_stream(), media_type="text/event-stream", headers=headers)


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
    # Provider keys, service secrets and engine choices are never returned here.
    return {
        r["key"]: r["value"]
        for r in rows
        if not r["key"].startswith(_HIDDEN_PREFIXES)
    }


@app.post("/api/settings")
def set_settings(payload: dict) -> dict:
    for k, v in payload.items():
        if v is None or str(k).startswith(_HIDDEN_PREFIXES):
            continue
        db.set_setting(str(k), str(v))
    return {"ok": True}


@app.get("/api/keys")
def get_service_keys() -> dict:
    """Masked status of non-LLM service keys (Hugging Face, Picovoice)."""
    return {"keys": service_keys.list_keys()}


@app.post("/api/keys/{name}")
def save_service_key(name: str, payload: ServiceKeyIn) -> JSONResponse:
    """Save or clear one service key. The secret itself is never echoed back."""
    if not service_keys.is_known(name):
        return JSONResponse({"error": "unknown key"}, status_code=404)
    if payload.clear_key:
        service_keys.delete_key(name)
    elif payload.api_key:
        service_keys.set_key(name, payload.api_key)
    return JSONResponse({"ok": True, "key": service_keys.status(name)})


@app.get("/api/engines")
def get_engines() -> dict:
    """Engine choices (cloud vs on-device) with options and defaults."""
    return {"engines": engines.snapshot()}


@app.post("/api/engines")
def set_engines(payload: EnginesIn) -> JSONResponse:
    """Persist engine choices; unknown components or values are rejected."""
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    bad = [
        f"{k}={v}"
        for k, v in updates.items()
        if not engines.valid(k, v)
    ]
    if bad:
        return JSONResponse(
            {"error": f"invalid engine choice(s): {', '.join(bad)}"},
            status_code=400,
        )
    for k, v in updates.items():
        engines.set(k, v)
    return JSONResponse({"ok": True, "engines": engines.snapshot()})


def _ondevice_error(exc: ondevice.OnDeviceError) -> JSONResponse:
    msg = str(exc)
    if msg.startswith("unknown model"):
        code = 404
    elif (
        msg.startswith("already")
        or msg.startswith("cancel the")
        or msg.startswith("no download")
        or msg.startswith("not enough")
    ):
        code = 409
    else:
        code = 400
    return JSONResponse({"ok": False, "error": msg}, status_code=code)


@app.get("/api/ondevice/info")
def ondevice_info() -> dict:
    """Device capability and engine state for the on-device LLM."""
    return {
        "device": ondevice.device_info(),
        "ready": ondevice.is_ready(),
        "loaded": ondevice.loaded_id(),
        "engine_mode": engines.get("llm"),
    }


@app.get("/api/ondevice/models")
def ondevice_models() -> dict:
    """Model catalogue with download, install and load state."""
    return {
        "models": ondevice.status(),
        "loaded": ondevice.loaded_id(),
        "ready": ondevice.is_ready(),
    }


@app.post("/api/ondevice/download")
def ondevice_download(payload: OnDeviceIn) -> JSONResponse:
    try:
        res = ondevice.start_download(payload.id or "")
    except ondevice.OnDeviceError as exc:
        return _ondevice_error(exc)
    return JSONResponse({"ok": True, **res}, status_code=202)


@app.post("/api/ondevice/cancel")
def ondevice_cancel(payload: OnDeviceIn) -> JSONResponse:
    try:
        res = ondevice.cancel_download(payload.id or "")
    except ondevice.OnDeviceError as exc:
        return _ondevice_error(exc)
    return JSONResponse({"ok": True, **res})


@app.post("/api/ondevice/delete")
def ondevice_delete(payload: OnDeviceIn) -> JSONResponse:
    try:
        res = ondevice.remove(payload.id or "")
    except ondevice.OnDeviceError as exc:
        return _ondevice_error(exc)
    return JSONResponse({"ok": True, **res})


@app.post("/api/ondevice/load")
async def ondevice_load(payload: OnDeviceIn) -> JSONResponse:
    try:
        res = await asyncio.to_thread(ondevice.load, payload.id or "")
    except ondevice.OnDeviceError as exc:
        return _ondevice_error(exc)
    return JSONResponse({"ok": True, **res})


@app.post("/api/ondevice/unload")
async def ondevice_unload() -> JSONResponse:
    try:
        res = await asyncio.to_thread(ondevice.unload)
    except ondevice.OnDeviceError as exc:
        return _ondevice_error(exc)
    return JSONResponse({"ok": True, **res})


@app.post("/api/ondevice/generate")
async def ondevice_generate(payload: OnDeviceIn) -> JSONResponse:
    prompt = (payload.prompt or "").strip()
    if not prompt:
        return JSONResponse(
            {"ok": False, "error": "prompt required"}, status_code=400
        )
    limit = max(16, min(int(payload.max_tokens or 512), 4096))
    try:
        text = await asyncio.to_thread(
            ondevice.chat,
            [{"role": "user", "content": prompt}],
            limit,
        )
    except ondevice.OnDeviceError as exc:
        return _ondevice_error(exc)
    return JSONResponse({"ok": True, "text": text, "provider": "on_device"})


# ---------------------------------------------------------------------------
# Voice (Phase 20): TTS, speech-to-text and the wake word
# ---------------------------------------------------------------------------
def _voice_error(message: str) -> JSONResponse:
    """Map voice failures to honest HTTP codes.

    409 = a prerequisite is missing (Android app, API key), 403 = permission
    denied on-device, 400 = anything else.
    """
    msg = str(message)
    if (
        "requires the Android app" in msg
        or "key is required" in msg
        or "needs a " in msg
    ):
        code = 409
    elif "permission" in msg:
        code = 403
    else:
        code = 400
    return JSONResponse({"ok": False, "error": msg}, status_code=code)


@app.get("/api/voice/status")
def get_voice_status() -> dict:
    """Combined voice report: providers, engine choice, wake-word state."""
    return voice.status_payload()


@app.post("/api/voice/speak")
def post_voice_speak(payload: VoiceIn) -> JSONResponse:
    """Speak text aloud (Android TTS on-device, ``say`` on macOS)."""
    text = (payload.text or "").strip()
    if not text:
        return JSONResponse(
            {"ok": False, "error": "text is required"}, status_code=400
        )
    text = text[: voice.MAX_SPEAK_CHARS]
    language = (payload.language or "").strip() or None
    try:
        if voice.is_android():
            data = voice.speak_text(text, language=language, rate=payload.rate or None)
            out = {
                "ok": True,
                "provider": data.get("provider", "android_tts"),
                "chars": len(text),
            }
            if "queued" in data:
                out["queued"] = bool(data["queued"])
            if data.get("language"):
                out["language"] = data["language"]
            return JSONResponse(out)
        manager = voice.VoiceManager()
        ok, message = manager.speak(
            text,
            voice=(payload.voice or None),
            rate=int(payload.rate) if payload.rate else None,
        )
        if not ok:
            return _voice_error(message)
        return JSONResponse(
            {
                "ok": True,
                "provider": getattr(manager.tts, "last_provider", None)
                or manager.tts.name,
                "chars": len(text),
            }
        )
    except voice.VoiceError as exc:
        return _voice_error(str(exc))


@app.post("/api/voice/stop")
def post_voice_stop() -> dict:
    """Stop any ongoing utterance."""
    try:
        voice.stop_speech()
        return {"ok": True}
    except voice.VoiceError as exc:
        return _voice_error(str(exc))


@app.get("/api/voice/voices")
def get_voice_voices(language: Optional[str] = None) -> dict:
    """TTS voices (Android engine voices, or macOS ``say`` voices)."""
    manager = voice.VoiceManager()
    if voice.is_android():
        names = voice.list_voices(language)
    else:
        names = manager.tts.voices()
    return {
        "ok": True,
        "provider": manager.tts.name,
        "count": len(names),
        "voices": names,
    }


@app.post("/api/voice/transcribe")
async def post_voice_transcribe(payload: VoiceIn) -> JSONResponse:
    """Transcribe live speech (mic) or a file, honouring ``engine.stt``.

    Live capture is blocking for up to ~30 s, so it runs off the event loop.
    """
    language = (payload.language or "").strip() or None
    path = (payload.audio_path or "").strip()
    try:
        if path:
            ok, text, provider = await asyncio.to_thread(
                voice.transcribe_file, path, language
            )
        else:
            seconds = max(1, min(int(payload.seconds or 8), 30))
            ok, text, provider = await asyncio.to_thread(
                voice.transcribe_live, language, seconds, None
            )
    except voice.VoiceError as exc:
        return _voice_error(str(exc))
    if not ok:
        return _voice_error(text)
    return JSONResponse(
        {"ok": True, "transcript": text, "provider": provider}
    )


@app.get("/api/wake/status")
def get_wake_status() -> dict:
    """Wake-word state: supported/running/keyword + key availability."""
    data = dict(voice.wake_status())
    data["key_set"] = bool(service_keys.get_key("picovoice"))
    data["keywords"] = voice.wake_keywords()
    return data


@app.post("/api/wake/start")
def post_wake_start(payload: WakeIn) -> JSONResponse:
    """Start listening for the wake word (needs the Android app + key)."""
    try:
        data = voice.wake_start(
            service_keys.get_key("picovoice") or "", payload.keyword
        )
    except voice.VoiceError as exc:
        return _voice_error(str(exc))
    out = {"ok": True}
    if "keyword" in data:
        out["keyword"] = data["keyword"]
    return JSONResponse(out)


@app.post("/api/wake/stop")
def post_wake_stop() -> JSONResponse:
    try:
        voice.wake_stop()
        return JSONResponse({"ok": True})
    except voice.VoiceError as exc:
        return _voice_error(str(exc))


# ---------------------------------------------------------------------------
# Memory ingestion & import (Phase 21)
# ---------------------------------------------------------------------------
@app.get("/api/memory")
def list_memory(
    query: Optional[str] = "",
    tag: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 50,
) -> dict:
    """Ranked memory items plus source/tag facets for the Memory tab."""
    items = memory_ingest.search(
        query=query or "", tags=tag or None, source=source or None, limit=limit
    )
    return {"count": len(items), "items": items, "stats": memory_ingest.stats()}


@app.get("/api/memory/stats")
def memory_stats() -> dict:
    return {"ok": True, **memory_ingest.stats()}


@app.post("/api/memory")
def add_memory(payload: MemoryIn) -> JSONResponse:
    """Store one explicit memory item (deduped by content)."""
    if not (payload.text or "").strip():
        return JSONResponse({"ok": False, "error": "text is required"}, status_code=400)
    item = memory_ingest.new_item(
        payload.text,
        key=payload.key or "",
        kind=payload.kind or "fact",
        source=payload.source or "",
        tags=payload.tags or "",
        session=payload.session or "",
    )
    counts = memory_ingest.store_items([item])
    return JSONResponse({"ok": True, "item": item, **counts})


@app.delete("/api/memory/{item_id}")
def delete_memory(item_id: str) -> JSONResponse:
    if not memory_ingest.delete_item(item_id):
        return JSONResponse({"ok": False, "error": "item not found"}, status_code=404)
    return JSONResponse({"ok": True, "item_id": item_id})


@app.post("/api/memory/ingest")
async def ingest_memory(payload: MemoryIngestIn) -> JSONResponse:
    """Extract and store facts from a block of text (heuristic or llm)."""
    if not (payload.text or "").strip():
        return JSONResponse({"ok": False, "error": "text is required"}, status_code=400)
    mode = (payload.mode or "heuristic").lower()
    if mode not in ("heuristic", "llm"):
        return JSONResponse(
            {"ok": False, "error": f"unknown mode: {mode}"}, status_code=400
        )
    result = await memory_ingest.aingest_text(
        payload.text,
        source=payload.source or "",
        tags=payload.tags or "",
        mode=mode,
        session=payload.session or "",
    )
    return JSONResponse({"ok": True, **result})


@app.post("/api/memory/import")
def import_memory(payload: MemoryImportIn) -> JSONResponse:
    """Import from a file path, an inline item list, or the legacy store."""
    try:
        if payload.path:
            result = memory_ingest.import_file(payload.path, source=payload.source)
        elif payload.legacy:
            result = memory_ingest.import_legacy_memory()
        elif payload.items is not None:
            result = memory_ingest.import_items(
                payload.items, source_override=payload.source
            )
        else:
            return JSONResponse(
                {"ok": False, "error": "provide path, items or legacy=true"},
                status_code=400,
            )
    except memory_ingest.MemoryError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, **result})


@app.get("/api/memory/export")
def export_memory() -> JSONResponse:
    items = memory_ingest.export_items()
    return JSONResponse(
        {"ok": True, "count": len(items), "items": items},
        headers={"Content-Disposition": 'attachment; filename="jarvis-memory.json"'},
    )


@app.post("/api/memory/delete-source")
def delete_memory_source(payload: MemorySourceIn) -> JSONResponse:
    if not (payload.source or "").strip():
        return JSONResponse({"ok": False, "error": "source is required"}, status_code=400)
    removed = memory_ingest.delete_source(payload.source)
    return JSONResponse({"ok": True, "source": payload.source, "removed": removed})


# ---------------------------------------------------------------------------
# WhatsApp bridge (Phase 22): live reading, rules, replies, import
# ---------------------------------------------------------------------------
def _whatsapp_error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": str(message)}, status_code=status)


@app.get("/api/whatsapp/status")
def whatsapp_status() -> dict:
    """Listener/reply support, settings, and stored-message counts."""
    return whatsapp.status_payload()


@app.get("/api/whatsapp/chats")
def whatsapp_chats(limit: int = 500) -> dict:
    """Mapped chat structure: counts, last activity, reply rule, suggestion."""
    rows = whatsapp.chats(limit)
    for row in rows:
        row["suggestion"] = whatsapp.get_suggestion(row["chat"])
    return {"ok": True, "count": len(rows), "chats": rows}


@app.get("/api/whatsapp/history")
def whatsapp_history(chat: str, limit: int = 100) -> JSONResponse:
    try:
        return JSONResponse({"ok": True, **whatsapp.history(chat, limit)})
    except whatsapp.WhatsAppError as exc:
        return _whatsapp_error(exc, exc.status)


@app.post("/api/whatsapp/event")
async def whatsapp_event(payload: WhatsAppEventIn) -> JSONResponse:
    """Record a live message (from the Android listener) and apply rules."""
    event = {
        "chat": payload.chat,
        "text": payload.text,
        "package": payload.package or "",
        "can_reply": bool(payload.can_reply),
        "ts_ms": payload.ts_ms,
        "ts": payload.ts or "",
        "sender": payload.sender or "",
    }
    try:
        result = await whatsapp.handle_event(event)
    except whatsapp.WhatsAppError as exc:
        return _whatsapp_error(exc, exc.status)
    return JSONResponse(result)


@app.post("/api/whatsapp/reply")
async def whatsapp_reply(payload: WhatsAppReplyIn) -> JSONResponse:
    """Send a reply through WhatsApp's reply action (Android only)."""
    try:
        data = await asyncio.to_thread(whatsapp.send_reply, payload.chat, payload.text)
    except whatsapp.WhatsAppError as exc:
        return _whatsapp_error(exc, exc.status)
    return JSONResponse({"ok": True, **data})


@app.post("/api/whatsapp/generate")
async def whatsapp_generate(payload: WhatsAppChatIn) -> JSONResponse:
    """Draft a style-matched reply for a chat and store it as a suggestion."""
    try:
        text = await whatsapp.generate_reply(payload.chat)
        suggestion = whatsapp.set_suggestion(payload.chat, text)
    except whatsapp.WhatsAppError as exc:
        return _whatsapp_error(exc, exc.status)
    return JSONResponse({"ok": True, **suggestion})


@app.post("/api/whatsapp/suggestion/accept")
async def whatsapp_accept(payload: WhatsAppChatIn) -> JSONResponse:
    try:
        data = await asyncio.to_thread(whatsapp.accept_suggestion, payload.chat)
    except whatsapp.WhatsAppError as exc:
        return _whatsapp_error(exc, exc.status)
    return JSONResponse({"ok": True, **data})


@app.post("/api/whatsapp/suggestion/dismiss")
def whatsapp_dismiss(payload: WhatsAppChatIn) -> JSONResponse:
    try:
        data = whatsapp.dismiss_suggestion(payload.chat)
    except whatsapp.WhatsAppError as exc:
        return _whatsapp_error(exc, exc.status)
    return JSONResponse({"ok": True, **data})


@app.post("/api/whatsapp/import")
def whatsapp_import(payload: WhatsAppImportIn) -> JSONResponse:
    """Import a WhatsApp "Export chat" .txt or .zip file."""
    try:
        result = whatsapp.import_export(payload.path, chat=payload.chat)
    except whatsapp.WhatsAppError as exc:
        return _whatsapp_error(exc, exc.status)
    return JSONResponse({"ok": True, **result})


@app.post("/api/whatsapp/settings")
def whatsapp_set_settings(payload: WhatsAppSettingsIn) -> JSONResponse:
    """Update listen/auto-reply/rules/cooldown settings."""
    try:
        effective = whatsapp.apply_settings(
            listen=payload.listen,
            auto_reply=payload.auto_reply,
            rules=payload.rules,
            cooldown=payload.cooldown,
        )
    except whatsapp.WhatsAppError as exc:
        return _whatsapp_error(exc, exc.status)
    return JSONResponse({"ok": True, **effective})


@app.delete("/api/whatsapp/chats/{chat}")
async def whatsapp_delete_chat(chat: str) -> JSONResponse:
    try:
        removed = await asyncio.to_thread(whatsapp.delete_chat, chat)
    except whatsapp.WhatsAppError as exc:
        return _whatsapp_error(exc, exc.status)
    return JSONResponse({"ok": True, "chat": chat, "removed": removed})


# ---------------------------------------------------------------------------
# Device control (Phase 24): consent-gated Android screen actions
# ---------------------------------------------------------------------------
def _device_error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": str(message)}, status_code=status)


@app.get("/api/device/status")
def device_status() -> dict:
    """Support, consent state, foreground app and audit count (never gated)."""
    return device_control.status_payload()


@app.post("/api/device/settings")
def device_set_settings(payload: DeviceSettingsIn) -> JSONResponse:
    """Turn the in-app master toggle on or off (Android access is granted separately)."""
    try:
        effective = device_control.apply_settings(enabled=payload.enabled)
    except device_control.DeviceError as exc:
        return _device_error(exc, exc.status)
    return JSONResponse({"ok": True, **effective})


@app.get("/api/device/audit")
def device_audit(limit: int = 100) -> dict:
    """Newest-first record of every action that reached the bridge."""
    rows = device_control.audit_log(limit)
    return {"ok": True, "count": len(rows), "total": device_control.audit_count(), "entries": rows}


@app.post("/api/device/action")
async def device_action(payload: DeviceActionIn) -> JSONResponse:
    """Run one whitelisted action; consent + validation gate before the bridge."""
    params: Dict[str, Any] = {}
    for key in ("x", "y", "index", "direction", "text", "max_chars", "max_nodes"):
        value = getattr(payload, key)
        if value is not None:
            params[key] = value
    try:
        data = await asyncio.to_thread(device_control.run_action, payload.action, params)
    except device_control.DeviceError as exc:
        return _device_error(exc, exc.status)
    return JSONResponse({"ok": True, **data})


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
