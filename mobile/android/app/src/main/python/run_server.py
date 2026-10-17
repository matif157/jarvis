"""Entry point for Android app to run embedded Jarvis server."""

import os
import threading

_started = False
_lock = threading.Lock()


def start(files_dir, host="127.0.0.1", port=8771):
    global _started
    with _lock:
        if _started:
            return
        _started = True

    os.makedirs(files_dir, exist_ok=True)
    os.environ.setdefault("JARVIS_DATA_DIR", os.path.join(files_dir, "data"))
    os.environ.setdefault("JARVIS_CONFIG_DIR", os.path.join(files_dir, "config"))
    os.makedirs(os.environ["JARVIS_DATA_DIR"], exist_ok=True)
    os.makedirs(os.environ["JARVIS_CONFIG_DIR"], exist_ok=True)

    import uvicorn
    from jarvis.app import app

    uvicorn.run(app, host=host, port=port, log_level="info", access_log=False)
