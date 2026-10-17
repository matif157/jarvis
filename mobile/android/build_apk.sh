#!/usr/bin/env bash
# Build the fully-offline Jarvis APK.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(cd ../.. && pwd)"  # jarvis root
SDK="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-}}"
BREW="$(command -v brew || echo /opt/homebrew/bin/brew)"

log() { printf '\n== %s\n' "$*"; }
need_cmd() { command -v "$1" >/dev/null 2>&1; }

if ! (java -version 2>&1 | grep -q version); then
  log "Installing JDK (Temurin 17)"
  "$BREW" install --cask temurin@17
  export JAVA_HOME="$(/usr/libexec/java_home -v 17)"
fi

if [ -z "$SDK" ] || [ ! -d "$SDK" ]; then
  if [ -d /opt/homebrew/share/android-commandlinetools ]; then
    SDK=/opt/homebrew/share/android-commandlinetools
  else
    log "Installing Android command-line tools"
    "$BREW" install --cask android-commandlinetools
    SDK=/opt/homebrew/share/android-commandlinetools
  fi
fi
export ANDROID_SDK_ROOT="$SDK"
export ANDROID_HOME="$SDK"
export PATH="$SDK/platform-tools:$SDK/cmdline-tools/latest/bin:$PATH"

log "Accepting SDK licenses and installing platform/build-tools"
yes | sdkmanager --licenses >/dev/null 2>&1 || true
sdkmanager "platform-tools" "platforms;android-34" "build-tools;34.0.0" >/dev/null

if ! need_cmd gradle; then
  if [ -x "$ANDROID_SDK_ROOT/gradle/bin/gradle" ]; then
    PATH="$ANDROID_SDK_ROOT/gradle/bin:$PATH"
  else
    "$BREW" install gradle
  fi
fi

log "Staging jarvis and web/ into app/src/main/python"
PYDEST="app/src/main/python"
rm -rf "$PYDEST/jarvis" "$PYDEST/web"
cp -R "$ROOT/jarvis" "$PYDEST/jarvis"
rm -rf "$PYDEST/jarvis/__pycache__"
cp -R "$ROOT/web" "$PYDEST/web" 2>/dev/null || true

log "Building debug APK"
gradle --no-daemon assembleDebug

APK="app/build/outputs/apk/debug/app-debug.apk"
[ -f "$APK" ] && log "Done: $APK" && echo "Install with: adb install -r $APK" || { echo "No APK found" >&2; exit 1; }
