package ai.jarvis.assistant.whatsapp;

import android.app.PendingIntent;
import android.app.RemoteInput;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;

import org.json.JSONObject;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Reply bridge for WhatsApp (Phase 22).
 *
 * <p>The {@link WhatsAppListener} saves, per chat, the first notification
 * action that exposes {@link RemoteInput} (the inline reply box). This class
 * turns {@code {"chat": ..., "text": ...}} from Python into a filled-in
 * intent sent through that action's {@link PendingIntent}, which types the
 * reply into WhatsApp's own reply flow - no automation or accessibility
 * service involved. JSON in / JSON out, like the voice bridges.
 */
public final class WhatsAppBridge {

    private static final Object LOCK = new Object();
    private static final long TARGET_TTL_MS = 6L * 60L * 60L * 1000L; // 6h
    private static final int TARGET_MAX = 200;

    private static Context appContext;
    private static final LinkedHashMap<String, Target> TARGETS =
            new LinkedHashMap<String, Target>(32, 0.75f, false) {
                @Override
                protected boolean removeEldestEntry(Map.Entry<String, Target> eldest) {
                    return size() > TARGET_MAX
                            || System.currentTimeMillis() - eldest.getValue().savedAt > TARGET_TTL_MS;
                }
            };

    private static final class Target {
        final PendingIntent pending;
        final RemoteInput[] inputs;
        final long savedAt;

        Target(PendingIntent pending, RemoteInput[] inputs, long savedAt) {
            this.pending = pending;
            this.inputs = inputs;
            this.savedAt = savedAt;
        }
    }

    private WhatsAppBridge() {
    }

    /** Called once from MainActivity so the bridge has an app context. */
    public static void attach(Context context) {
        synchronized (LOCK) {
            if (appContext == null) {
                appContext = context.getApplicationContext();
            }
        }
    }

    /** Record the reply target of one chat (called by the listener). */
    static void saveReplyTarget(String chat, PendingIntent pending,
                                RemoteInput[] inputs, long savedAt) {
        if (chat == null || chat.isEmpty() || pending == null || inputs == null) {
            return;
        }
        synchronized (LOCK) {
            TARGETS.put(chat, new Target(pending, inputs, savedAt));
        }
    }

    /** Drop a chat's target when its notification goes away. */
    static void clearReplyTarget(String chat) {
        if (chat == null) {
            return;
        }
        synchronized (LOCK) {
            TARGETS.remove(chat);
        }
    }

    private static Target takeTarget(String chat) {
        synchronized (LOCK) {
            Target target = TARGETS.get(chat);
            if (target == null) {
                return null;
            }
            if (System.currentTimeMillis() - target.savedAt > TARGET_TTL_MS) {
                TARGETS.remove(chat);
                return null;
            }
            return target;
        }
    }

    /**
     * {"chat": "...", "text": "..."} -> {ok, chat} / error.
     *
     * <p>Fills the saved {@link RemoteInput} results and fires the original
     * reply action's pending intent; WhatsApp delivers the message itself.
     */
    public static String reply(String requestJson) {
        try {
            JSONObject request = new JSONObject(
                    requestJson == null || requestJson.isEmpty() ? "{}" : requestJson);
            String chat = request.optString("chat", "").trim();
            String text = request.optString("text", "").trim();
            if (chat.isEmpty()) {
                return error("chat is required");
            }
            if (text.isEmpty()) {
                return error("reply text is required");
            }
            if (appContext == null) {
                return error("requires the Android app");
            }
            Target target = takeTarget(chat);
            if (target == null) {
                return error("no open reply target for this chat - open the chat in WhatsApp first");
            }

            Bundle results = new Bundle();
            results.putCharSequence(target.inputs[0].getResultKey(), text);
            Intent fillIn = new Intent();
            RemoteInput.addResultsToIntent(target.inputs, fillIn, results);
            target.pending.send(appContext, 0, fillIn);
            return new JSONObject()
                    .put("ok", true)
                    .put("chat", chat)
                    .put("provider", "whatsapp_reply")
                    .toString();
        } catch (PendingIntent.CanceledException ce) {
            return error("reply target expired - open the chat in WhatsApp again");
        } catch (Throwable t) {
            return error(describe(t));
        }
    }

    /**
     * {ok, supported, listener, targets: [chats]} - consumed by
     * {@code GET /api/whatsapp/status} and the reply rules.
     */
    public static String status() {
        JSONObject out = new JSONObject();
        try {
            out.put("ok", true);
            out.put("supported", true);
            out.put("listener", WhatsAppListener.isRunning());
            List<String> chats = new ArrayList<>();
            synchronized (LOCK) {
                for (Map.Entry<String, Target> entry : TARGETS.entrySet()) {
                    if (System.currentTimeMillis() - entry.getValue().savedAt <= TARGET_TTL_MS) {
                        chats.add(entry.getKey());
                    }
                }
            }
            out.put("targets", new org.json.JSONArray(chats));
        } catch (Throwable t) {
            return error(describe(t));
        }
        return out.toString();
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
