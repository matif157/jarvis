package ai.jarvis.assistant.voice;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;

import org.json.JSONObject;

import ai.jarvis.assistant.MainActivity;
import ai.picovoice.porcupine.Porcupine;
import ai.picovoice.porcupine.PorcupineManager;
import ai.picovoice.porcupine.PorcupineManagerCallback;

/**
 * Wake-word bridge (Porcupine) for the Python app.
 *
 * <p>Starts an always-on listener for a built-in keyword (default "jarvis")
 * and reports detections to the WebView through
 * {@code MainActivity.notifyWake}, which runs
 * {@code window.onJarvisWake(keyword)} in page JS. Access keys come from the
 * Python settings store (never hard-coded).
 */
public final class WakeBridge {

    private static final Object LOCK = new Object();

    private static Context appContext;
    private static PorcupineManager manager;
    private static String activeKeyword;

    private WakeBridge() {
    }

    /** Called once from MainActivity with an application context. */
    public static void attach(Context context) {
        synchronized (LOCK) {
            if (appContext == null) {
                appContext = context.getApplicationContext();
            }
        }
    }

    private static boolean micGranted() {
        return appContext != null
                && appContext.checkSelfPermission(Manifest.permission.RECORD_AUDIO)
                        == PackageManager.PERMISSION_GRANTED;
    }

    /**
     * {"access_key": "...", "keyword": "jarvis"} -> {ok, keyword} / error.
     * Requires the microphone permission.
     */
    public static String start(String requestJson) {
        synchronized (LOCK) {
            try {
                JSONObject request = new JSONObject(
                        requestJson == null || requestJson.isEmpty() ? "{}" : requestJson);
                String accessKey = request.optString("access_key", "").trim();
                if (accessKey.isEmpty()) {
                    return error("access key required");
                }
                if (appContext == null) {
                    return error("the on-device engine requires the Android app");
                }
                if (!micGranted()) {
                    return error("microphone permission not granted");
                }

                String keyword = request.optString("keyword", "jarvis").toLowerCase();
                if (!isKnownKeyword(keyword)) {
                    return error("unknown keyword: " + keyword);
                }

                stopLocked();

                Porcupine.BuiltInKeyword builtIn =
                        Porcupine.BuiltInKeyword.valueOf(keyword.toUpperCase());
                final String detected = keyword;
                PorcupineManagerCallback callback = keywordIndex ->
                        MainActivity.notifyWake(detected);

                manager = new PorcupineManager.Builder()
                        .setAccessKey(accessKey)
                        .setKeyword(builtIn)
                        .setSensitivity(0.6f)
                        .build(appContext, callback);
                manager.start();

                activeKeyword = keyword;
                return new JSONObject()
                        .put("ok", true)
                        .put("keyword", keyword)
                        .toString();
            } catch (Throwable t) {
                stopLocked();
                return error(describe(t));
            }
        }
    }

    /** Stop listening. Idempotent. */
    public static String stop() {
        synchronized (LOCK) {
            stopLocked();
        }
        try {
            return new JSONObject().put("ok", true).toString();
        } catch (Throwable t) {
            return "{\"ok\":true}";
        }
    }

    /** {ok, running, keyword, supported} */
    public static String status() {
        synchronized (LOCK) {
            JSONObject out = new JSONObject();
            try {
                out.put("ok", true);
                out.put("supported", true);
                boolean running = manager != null;
                out.put("running", running);
                out.put("keyword", activeKeyword == null ? "" : activeKeyword);
                out.put("mic_granted", micGranted());
            } catch (Throwable t) {
                return "{\"ok\":false,\"error\":\"bridge error\"}";
            }
            return out.toString();
        }
    }

    /** Built-in keywords shipped with the Porcupine Android SDK. */
    public static String keywords() {
        StringBuilder sb = new StringBuilder("[");
        String[] list = {"jarvis", "computer", "porcupine", "bumblebee", "alexa",
                "terminator", "picovoice", "grasshopper", "grapefruit", "americano",
                "blueberry", "hey_google", "ok_google", "hey_siri"};
        for (int i = 0; i < list.length; i++) {
            if (i > 0) {
                sb.append(',');
            }
            sb.append('"').append(list[i]).append('"');
        }
        sb.append(']');
        try {
            return new JSONObject().put("ok", true)
                    .put("keywords", new org.json.JSONArray(sb.toString())).toString();
        } catch (Throwable t) {
            return "{\"ok\":false,\"error\":\"bridge error\"}";
        }
    }

    private static boolean isKnownKeyword(String keyword) {
        String[] list = {"jarvis", "computer", "porcupine", "bumblebee", "alexa",
                "terminator", "picovoice", "grasshopper", "grapefruit", "americano",
                "blueberry", "hey_google", "ok_google", "hey_siri"};
        for (String candidate : list) {
            if (candidate.equals(keyword)) {
                return true;
            }
        }
        return false;
    }

    private static void stopLocked() {
        if (manager != null) {
            try {
                manager.stop();
            } catch (Throwable ignored) {
                // best effort
            }
            try {
                manager.delete();
            } catch (Throwable ignored) {
                // best effort
            }
            manager = null;
        }
        activeKeyword = null;
    }

    private static String error(String message) {
        JSONObject out = new JSONObject();
        try {
            out.put("ok", false);
            out.put("error", message);
        } catch (Throwable t) {
            return "{\"ok\":false,\"error\":\"bridge error\"}";
        }
        return out.toString();
    }

    private static String describe(Throwable t) {
        String message = t.getMessage();
        String name = t.getClass().getSimpleName();
        if (message == null || message.isEmpty()) {
            return name;
        }
        if (message.length() > 200) {
            message = message.substring(0, 200);
        }
        return name + ": " + message;
    }
}
