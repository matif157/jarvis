"""On-device LLM support: LiteRT-LM engine bridge + model download manager.

Models are ``.litertlm`` files from the HuggingFace LiteRT Community. They are
downloaded once into ``<data dir>/models`` with progress, then loaded into the
LiteRT-LM engine through a small Java bridge (``ai.jarvis.assistant.llm.
OnDeviceLlm``) that only exists inside the Android app.

Desktop behaviour: the catalogue, download manager and status endpoints all
work (useful for pre-staging files), but generation reports that the on-device
engine requires the Android app. Tests inject a fake bridge with
:func:`set_backend`.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx

from .config import get_data_dir

CHUNK = 1024 * 256
SYSTEM_PROMPT = "You are Jarvis, a concise, helpful personal assistant."

CATALOG: List[Dict[str, Any]] = [
    {
        "id": "gemma3-270m",
        "label": "Gemma 3 270M",
        "description": "Smallest and fastest - recommended for this phone.",
        "repo": "litert-community/gemma-3-270m-it",
        "file": "gemma3-270m-it-q8.litertlm",
        "size": 304005120,
        "min_ram_gb": 2,
    },
    {
        "id": "gemma3-1b",
        "label": "Gemma 3 1B",
        "description": "Smarter, needs more memory and a bigger device.",
        "repo": "litert-community/Gemma3-1B-IT",
        "file": "gemma3-1b-it-int4.litertlm",
        "size": 584417280,
        "min_ram_gb": 4,
    },
    {
        "id": "gemma4-e2b",
        "label": "Gemma 4 E2B",
        "description": "Newest generation - large download, 8 GB+ devices.",
        "repo": "litert-community/gemma-4-E2B-it-litert-lm",
        "file": "gemma-4-E2B-it.litertlm",
        "size": 2588147712,
        "min_ram_gb": 8,
    },
]

_lock = threading.Lock()
_downloads: Dict[str, Dict[str, Any]] = {}
_loaded_id: Optional[str] = None
_backend_override: Optional[Any] = None
_bridge_cache: Any = None
_bridge_probed = False


class OnDeviceError(RuntimeError):
    """Raised when the on-device engine cannot satisfy a request."""


def model_dir() -> Path:
    d = Path(get_data_dir()) / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def entry(model_id: str) -> Optional[Dict[str, Any]]:
    for e in CATALOG:
        if e["id"] == model_id:
            return e
    return None


def download_url(e: Dict[str, Any]) -> str:
    if e.get("url"):
        return str(e["url"])
    return f"https://huggingface.co/{e['repo']}/resolve/main/{e['file']}"


def file_path(model_id: str) -> Path:
    return model_dir() / f"{model_id}.litertlm"


def part_path(model_id: str) -> Path:
    return model_dir() / f"{model_id}.litertlm.part"


def installed_size(model_id: str) -> Optional[int]:
    try:
        p = file_path(model_id)
        return p.stat().st_size if p.is_file() else None
    except OSError:
        return None


def set_backend(backend: Any) -> None:
    """Install a bridge stand-in (tests). Object mirrors the Kotlin API."""
    global _backend_override
    _backend_override = backend


def clear_backend() -> None:
    global _backend_override, _bridge_probed, _bridge_cache
    _backend_override = None
    _bridge_probed = False
    _bridge_cache = None


def _backend() -> Any:
    global _bridge_probed, _bridge_cache
    if _backend_override is not None:
        return _backend_override
    if not _bridge_probed:
        _bridge_probed = True
        try:
            from ai.jarvis.assistant.llm import OnDeviceLlm  # type: ignore

            _bridge_cache = OnDeviceLlm
        except Exception:  # noqa: BLE001 - not running inside the Android app
            _bridge_cache = None
    return _bridge_cache


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, str):
        try:
            data = json.loads(value)
            return data if isinstance(data, dict) else {"ok": False, "error": "bad bridge payload"}
        except Exception:  # noqa: BLE001
            return {"ok": False, "error": value[:200]}
    if isinstance(value, dict):
        return value
    return {"ok": False, "error": "unexpected bridge return"}


def is_ready() -> bool:
    b = _backend()
    if b is None:
        return False
    try:
        return bool(b.isLoaded())
    except Exception:  # noqa: BLE001
        return False


def loaded_id() -> Optional[str]:
    return _loaded_id if is_ready() else None


def device_info() -> Dict[str, Any]:
    b = _backend()
    if b is None:
        mem = _host_memory_bytes()
        return {
            "supported": False,
            "platform": "host",
            "reason": "On-device chat runs in the Android app; "
            "downloads and staging work here.",
            "mem_total_bytes": mem,
        }
    try:
        info = _as_dict(b.deviceInfo())
    except Exception as exc:  # noqa: BLE001
        return {"supported": False, "platform": "unknown", "error": str(exc)}
    info.setdefault("supported", True)
    info.setdefault("platform", "android")
    return info


def _host_memory_bytes() -> Optional[int]:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        total = int(pages) * int(page_size)
        return total if total > 0 else None
    except Exception:  # noqa: BLE001 - platform without sysconf limits
        return None


def status() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for e in CATALOG:
        with _lock:
            dl = _downloads.get(e["id"])
        installed = installed_size(e["id"]) is not None
        partial = 0
        p = part_path(e["id"])
        try:
            if p.is_file():
                partial = p.stat().st_size
        except OSError:
            pass
        item = {
            "id": e["id"],
            "label": e["label"],
            "description": e["description"],
            "size": e["size"],
            "min_ram_gb": e["min_ram_gb"],
            "installed": installed,
            "installed_bytes": installed_size(e["id"]),
            "partial_bytes": partial,
            "loaded": _loaded_id == e["id"] and installed,
            "state": (dl or {}).get("state", "idle"),
            "progress": (dl or {}).get("progress", 0.0 if not installed else 100.0),
            "done_bytes": (dl or {}).get("done", 0),
            "error": (dl or {}).get("error"),
        }
        out.append(item)
    return out


def _hf_token() -> Optional[str]:
    try:
        from . import service_keys

        return service_keys.get_key("hf") or None
    except Exception:  # noqa: BLE001
        return None


def _free_bytes() -> Optional[int]:
    try:
        st = os.statvfs(model_dir())
        return int(st.f_bavail) * int(st.f_frsize)
    except Exception:  # noqa: BLE001
        return None


def start_download(model_id: str) -> Dict[str, Any]:
    e = entry(model_id)
    if e is None:
        raise OnDeviceError("unknown model")

    with _lock:
        dl = _downloads.get(model_id)
        if dl and dl.get("state") == "downloading":
            raise OnDeviceError("already downloading")
        if installed_size(model_id) is not None:
            raise OnDeviceError("already installed")

        free = _free_bytes()
        if free is not None and free < int(e["size"]) + 64 * 1024 * 1024:
            raise OnDeviceError(
                f"not enough free space: need about "
                f"{int(e['size']) // (1024 * 1024) + 64} MB"
            )

        state = {
            "state": "downloading",
            "done": 0,
            "total": int(e["size"]),
            "progress": 0.0,
            "error": None,
            "cancel": False,
            "started_at": time.time(),
        }
        _downloads[model_id] = state

    thread = threading.Thread(
        target=_download_worker, args=(e, state), daemon=True, name=f"odl-{model_id}"
    )
    thread.start()
    return {"ok": True, "id": model_id}


def _download_worker(e: Dict[str, Any], state: Dict[str, Any]) -> None:
    model_id = e["id"]
    part = part_path(model_id)
    url = download_url(e)
    headers = {}
    token = _hf_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with httpx.Client(timeout=httpx.Timeout(30.0, connect=15.0), follow_redirects=True) as client:
            with client.stream("GET", url, headers=headers) as r:
                if r.status_code in (401, 403):
                    raise OnDeviceError(
                        "Hugging Face requires a token and one-time license "
                        "acceptance for this model. Set your token in "
                        "Settings - Service API keys (hf), accept the Gemma "
                        "license on huggingface.co, then retry."
                    )
                if r.status_code != 200:
                    raise OnDeviceError(f"download failed: HTTP {r.status_code}")

                total = int(r.headers.get("content-length") or 0) or int(e["size"])
                with open(part, "wb") as fh:
                    done = 0
                    last = time.monotonic()
                    window = 0
                    for chunk in r.iter_bytes(CHUNK):
                        if state.get("cancel"):
                            raise OnDeviceError("cancelled")
                        fh.write(chunk)
                        done += len(chunk)
                        window += len(chunk)
                        now = time.monotonic()
                        if now - last >= 0.5:
                            state["speed_bps"] = int(window / (now - last))
                            last, window = now, 0
                        state["done"] = done
                        state["total"] = total
                        state["progress"] = round(min(100.0, done * 100.0 / total), 1)
                    fh.flush()
                    os.fsync(fh.fileno())

        final = file_path(model_id)
        os.replace(part, final)
        size = final.stat().st_size
        expected = int(e["size"])
        with _lock:
            state["state"] = "done"
            state["progress"] = 100.0
            state["done"] = size
            state["verified"] = size == expected
            if size != expected:
                state["error"] = f"size differs from catalogue ({size} vs {expected} bytes)"
    except OnDeviceError as exc:
        cancelled = str(exc) == "cancelled"
        with _lock:
            state["state"] = "cancelled" if cancelled else "error"
            state["error"] = None if cancelled else str(exc)
            if cancelled:
                state["progress"] = 0.0
        try:
            if cancelled and part.exists():
                part.unlink()
        except OSError:
            pass
    except Exception as exc:  # noqa: BLE001
        with _lock:
            state["state"] = "error"
            state["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"


def cancel_download(model_id: str) -> Dict[str, Any]:
    if entry(model_id) is None:
        raise OnDeviceError("unknown model")
    with _lock:
        dl = _downloads.get(model_id)
        if not dl or dl.get("state") != "downloading":
            raise OnDeviceError("no download in progress")
        dl["cancel"] = True
    return {"ok": True, "id": model_id}


def remove(model_id: str) -> Dict[str, Any]:
    if entry(model_id) is None:
        raise OnDeviceError("unknown model")
    with _lock:
        dl = _downloads.get(model_id)
        if dl and dl.get("state") == "downloading":
            raise OnDeviceError("cancel the download first")
    removed = False
    for p in (file_path(model_id), part_path(model_id)):
        try:
            if p.is_file():
                p.unlink()
                removed = True
        except OSError:
            pass
    global _loaded_id
    with _lock:
        _downloads.pop(model_id, None)
        if _loaded_id == model_id:
            _loaded_id = None
    return {"ok": True, "id": model_id, "removed": removed}


def load(model_id: str) -> Dict[str, Any]:
    e = entry(model_id)
    if e is None:
        raise OnDeviceError("unknown model")
    if installed_size(model_id) is None:
        raise OnDeviceError("model not downloaded yet")
    b = _backend()
    if b is None:
        raise OnDeviceError("the on-device engine requires the Android app")
    global _loaded_id
    result = _as_dict(b.load(str(file_path(model_id))))
    if not result.get("ok"):
        raise OnDeviceError(str(result.get("error") or "failed to load model"))
    _loaded_id = model_id
    return {"ok": True, "id": model_id, "detail": result}


def unload() -> Dict[str, Any]:
    global _loaded_id
    b = _backend()
    if b is None:
        raise OnDeviceError("the on-device engine requires the Android app")
    result = _as_dict(b.unload())
    _loaded_id = None
    if not result.get("ok"):
        raise OnDeviceError(str(result.get("error") or "failed to unload"))
    return {"ok": True}


def chat(messages: List[Dict[str, Any]], max_tokens: int = 512) -> str:
    b = _backend()
    if b is None:
        raise OnDeviceError("the on-device engine requires the Android app")
    if not is_ready():
        raise OnDeviceError("no on-device model loaded")
    payload = {
        "messages": [
            {"role": m.get("role", "user"), "content": str(m.get("content") or "")}
            for m in messages
        ],
        "max_tokens": int(max_tokens),
        "system": SYSTEM_PROMPT,
    }
    result = _as_dict(b.generate(json.dumps(payload)))
    if not result.get("ok"):
        raise OnDeviceError(str(result.get("error") or "generation failed"))
    text = str(result.get("text") or "")
    if not text.strip():
        raise OnDeviceError("on-device model returned empty text")
    return text.strip()


def reset_state() -> None:
    """Clear runtime state (tests)."""
    global _loaded_id
    with _lock:
        _downloads.clear()
    _loaded_id = None
