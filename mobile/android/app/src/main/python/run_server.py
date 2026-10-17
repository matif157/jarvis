"""Entry point for Android app to run embedded Jarvis server."""

import os
import sys
import threading
import time

_started = False
_lock = threading.Lock()


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

    try:
        import uvicorn
        from jarvis.app import app

        def _run():
            try:
                # Run in blocking mode - critical for server to bind
                uvicorn.run(app, host=host, port=port, log_level="error", access_log=False)
            except Exception as e:
                print("UVICORN_ERROR:", e, file=sys.stderr)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        # Give server time to start up
        time.sleep(2)
    except Exception as e:
        print("SERVER_START_ERROR:", e, file=sys.stderr)
