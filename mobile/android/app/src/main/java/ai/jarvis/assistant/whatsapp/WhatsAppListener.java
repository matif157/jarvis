package ai.jarvis.assistant.whatsapp;

import android.app.Notification;
import android.os.Bundle;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;

import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Reads WhatsApp messages from posted notifications (Phase 22).
 *
 * <p>Only WhatsApp (and WhatsApp Business) notifications that carry a chat
 * title and message body are forwarded. Each message is de-duplicated per
 * notification key and POSTed as JSON to the local Python server
 * ({@code /api/whatsapp/event}), which decides what to record and whether the
 * reply rules allow a response. The first action that exposes remote inputs
 * (the inline reply box) is saved through {@link WhatsAppBridge} so replies
 * can be sent back into the very same conversation.
 */
public class WhatsAppListener extends NotificationListenerService {

    private static final String TAG = "JarvisWAListener";
    private static final String EVENT_URL = "http://127.0.0.1:8771/api/whatsapp/event";
    private static final String[] PACKAGES = {"com.whatsapp", "com.whatsapp.w4b"};
    private static final int DEDUPE_MAX = 300;
    private static final int POST_ATTEMPTS = 3;

    private static volatile boolean running;

    /** Bounded set of already-forwarded {@code key|chat|body} triples. */
    private static final LinkedHashMap<String, Boolean> SEEN =
            new LinkedHashMap<String, Boolean>(64, 0.75f, false) {
                @Override
                protected boolean removeEldestEntry(Map.Entry<String, Boolean> eldest) {
                    return size() > DEDUPE_MAX;
                }
            };

    private final ExecutorService executor = Executors.newSingleThreadExecutor();

    static boolean isRunning() {
        return running;
    }

    @Override
    public void onListenerConnected() {
        running = true;
    }

    @Override
    public void onDestroy() {
        running = false;
        executor.shutdownNow();
        super.onDestroy();
    }

    @Override
    public void onNotificationPosted(StatusBarNotification sbn) {
        try {
            forward(sbn);
        } catch (Throwable t) {
            // a malformed notification must never crash the listener
        }
    }

    @Override
    public void onNotificationRemoved(StatusBarNotification sbn, RankingMap rankingMap, int reason) {
        try {
            if (sbn != null && sbn.getNotification() != null && isWhatsApp(sbn.getPackageName())) {
                Bundle extras = sbn.getNotification().extras;
                String chat = clean(first(
                        extras.getCharSequence("android.conversationTitle"),
                        extras.getCharSequence("android.title")));
                if (!chat.isEmpty()) {
                    WhatsAppBridge.clearReplyTarget(chat);
                }
            }
        } catch (Throwable t) {
            // best effort
        }
        super.onNotificationRemoved(sbn, rankingMap, reason);
    }

    private void forward(StatusBarNotification sbn) {
        if (sbn == null || sbn.getNotification() == null || !isWhatsApp(sbn.getPackageName())) {
            return;
        }
        Notification n = sbn.getNotification();
        if ((n.flags & Notification.FLAG_GROUP_SUMMARY) != 0
                || (n.flags & Notification.FLAG_ONGOING_EVENT) != 0) {
            return;
        }
        Bundle extras = n.extras;
        String chat = clean(first(
                extras.getCharSequence("android.conversationTitle"),
                extras.getCharSequence("android.title")));
        String body = clean(first(
                extras.getCharSequence("android.bigText"),
                extras.getCharSequence("android.text")));
        if (chat.isEmpty() || body.isEmpty()) {
            return;
        }
        String key = String.valueOf(sbn.getKey()) + "|" + chat + "|" + body;
        if (!markSeen(key)) {
            return;
        }

        Notification.Action reply = findReplyAction(n);
        boolean canReply = reply != null && reply.actionIntent != null
                && reply.getRemoteInputs() != null && reply.getRemoteInputs().length > 0;
        if (canReply) {
            WhatsAppBridge.saveReplyTarget(chat, reply.actionIntent,
                    reply.getRemoteInputs(), System.currentTimeMillis());
        }

        String json;
        try {
            JSONObject payload = new JSONObject();
            payload.put("chat", chat);
            payload.put("text", body);
            payload.put("package", sbn.getPackageName());
            payload.put("can_reply", canReply);
            long posted = sbn.getPostTime();
            payload.put("ts_ms", posted > 0 ? posted : System.currentTimeMillis());
            payload.put("notification", String.valueOf(sbn.getKey()));
            json = payload.toString();
        } catch (Throwable t) {
            return;
        }

        executor.execute(() -> postEvent(json));
    }

    private static boolean isWhatsApp(String packageName) {
        if (packageName == null) {
            return false;
        }
        for (String candidate : PACKAGES) {
            if (candidate.equals(packageName)) {
                return true;
            }
        }
        return false;
    }

    private static synchronized boolean markSeen(String key) {
        if (SEEN.containsKey(key)) {
            return false;
        }
        SEEN.put(key, Boolean.TRUE);
        return true;
    }

    private static Notification.Action findReplyAction(Notification n) {
        if (n.actions == null) {
            return null;
        }
        for (Notification.Action action : n.actions) {
            if (action != null && action.actionIntent != null
                    && action.getRemoteInputs() != null && action.getRemoteInputs().length > 0) {
                return action;
            }
        }
        return null;
    }

    private static String first(CharSequence a, CharSequence b) {
        if (a != null && a.length() > 0) {
            return a.toString();
        }
        return b == null ? "" : b.toString();
    }

    /** Strip bidi marks WhatsApp puts around contact names, collapse space. */
    private static String clean(String value) {
        if (value == null) {
            return "";
        }
        String out = value.replace("\u200e", "").replace("\u200f", "").replace('\n', ' ').trim();
        return out.length() > 4000 ? out.substring(0, 4000) : out;
    }

    private void postEvent(String json) {
        for (int attempt = 1; attempt <= POST_ATTEMPTS; attempt++) {
            HttpURLConnection conn = null;
            try {
                byte[] body = json.getBytes(StandardCharsets.UTF_8);
                conn = (HttpURLConnection) new URL(EVENT_URL).openConnection();
                conn.setConnectTimeout(2000);
                conn.setReadTimeout(3000);
                conn.setRequestMethod("POST");
                conn.setDoOutput(true);
                conn.setRequestProperty("Content-Type", "application/json");
                conn.setFixedLengthStreamingMode(body.length);
                try (OutputStream out = conn.getOutputStream()) {
                    out.write(body);
                }
                int code = conn.getResponseCode();
                if (code >= 200 && code < 300) {
                    return;
                }
            } catch (Exception e) {
                Logd("post attempt " + attempt + " failed: " + e);
            } finally {
                if (conn != null) {
                    conn.disconnect();
                }
            }
            try {
                Thread.sleep(200L * attempt);
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                return;
            }
        }
        Logd("giving up after " + POST_ATTEMPTS + " attempts");
    }

    private static void Logd(String message) {
        try {
            android.util.Log.d(TAG, message);
        } catch (Throwable ignored) {
            // logging is best effort
        }
    }
}
