"""Entry point for Android app to run embedded Jarvis server."""

import os
import sys
import threading
import traceback

_started = False
_lock = threading.Lock()
_last_error = ""


def _record_error(exc: BaseException) -> None:
    global _last_error
    _last_error = "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    )
    print("JARVIS_SERVER_ERROR:\n" + _last_error, file=sys.stderr)
    sys.stderr.flush()


def get_status():
    """Return server startup status for on-device diagnostics."""
    return {
        "started": _started,
        "running": _started and not _last_error,
        "error": _last_error,
    }


def start(files_dir, host="127.0.0.1", port=8771):
    global _started
    with _lock:
        if _started:
            return
        _started = True

    os.makedirs(files_dir, exist_ok=True)
    data_dir = os.path.join(files_dir, "data")
    config_dir = os.path.join(files_dir, "config")
    os.environ.setdefault("JARVIS_DATA_DIR", data_dir)
    os.environ.setdefault("JARVIS_CONFIG_DIR", config_dir)
    os.environ.setdefault("JARVIS_HOST", host)
    os.environ.setdefault("JARVIS_PORT", str(port))
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(config_dir, exist_ok=True)

    # Ensure module path includes the bundled dirs
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    if pkg_dir not in sys.path:
        sys.path.insert(0, pkg_dir)

    try:
        import uvicorn

        from jarvis.app import app

        def _run():
            try:
                log_level = os.environ.get("JARVIS_UVICORN_LOG", "error")
                access_log = os.environ.get("JARVIS_UVICORN_ACCESS", "0") in ("1", "true", "yes")
                config = uvicorn.Config(app, host=host, port=port, log_level=log_level, access_log=access_log)
                server = uvicorn.Server(config)
                server.run()
            except Exception as e:  # pragma: no cover - device only
                _record_error(e)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
    except Exception as e:  # pragma: no cover - device only
        _record_error(e)
