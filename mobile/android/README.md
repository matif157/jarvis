# Jarvis — Android (offline-capable, embedded Python)

Builds an Android APK that embeds Jarvis (FastAPI server) via Chaquopy and loads it in a WebView.

## Build
```sh
./build_apk.sh
# -> app/build/outputs/apk/debug/app-debug.apk
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

The script installs JDK 17, Android command-line tools, and Gradle if needed; accepts licenses; stages jarvis/ + web/ into app/src/main/python; builds debug APK.

## Notes
- Server runs on http://127.0.0.1:8771
- Data/config stored in app files dir (survives restarts)
- Uses Chaquopy Python 3.12; pip installs fastapi/uvicorn/httpx/pydantic/jinja2/python-dotenv
