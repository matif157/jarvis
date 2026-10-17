package ai.jarvis.assistant.llm;

import android.os.Build;

import com.google.ai.edge.litertlm.Backend;
import com.google.ai.edge.litertlm.Contents;
import com.google.ai.edge.litertlm.Conversation;
import com.google.ai.edge.litertlm.ConversationConfig;
import com.google.ai.edge.litertlm.Engine;
import com.google.ai.edge.litertlm.EngineConfig;
import com.google.ai.edge.litertlm.Message;
import com.google.ai.edge.litertlm.SamplerConfig;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.util.ArrayList;
import java.util.List;

/**
 * Thin bridge between the Python app (Chaquopy) and the LiteRT-LM engine.
 *
 * <p>Python imports this class as {@code ai.jarvis.assistant.llm.OnDeviceLlm}
 * and calls the static methods; every method returns a JSON string so the
 * Python side never has to deal with Java/Kotlin types. CPU-only, one loaded
 * model at a time, generation is serialised by {@link #LOCK} and runs on the
 * calling (worker) thread.
 */
public final class OnDeviceLlm {

    private static final Object LOCK = new Object();
    private static final String SYSTEM_PROMPT =
            "You are Jarvis, a concise, helpful personal assistant.";

    private static Engine engine;
    private static Conversation conversation;
    private static String loadedPath;

    private OnDeviceLlm() {
    }

    /** True when a model is loaded and its native conversation is alive. */
    public static boolean isLoaded() {
        synchronized (LOCK) {
            return conversation != null && conversation.isAlive();
        }
    }

    /** JSON description of the device, used by the Settings screen. */
    public static String deviceInfo() {
        JSONObject out = new JSONObject();
        try {
            out.put("supported", true);
            out.put("platform", "android");
            out.put("mem_total_bytes", totalMemoryBytes());
            JSONArray abis = new JSONArray();
            if (Build.SUPPORTED_ABIS != null) {
                for (String abi : Build.SUPPORTED_ABIS) {
                    abis.put(abi);
                }
            }
            out.put("abis", abis);
            out.put("sdk", Build.VERSION.SDK_INT);
        } catch (Throwable t) {
            return error("deviceInfo failed: " + describe(t));
        }
        return out.toString();
    }

    /** Load a downloaded {@code .litertlm} file. Returns JSON. */
    public static String load(String path) {
        synchronized (LOCK) {
            try {
                File file = new File(path);
                if (!file.isFile()) {
                    return error("model file not found: " + path);
                }
                unloadLocked();

                Engine next = new Engine(new EngineConfig(path, new Backend.CPU()));
                next.initialize();

                engine = next;
                loadedPath = path;

                JSONObject out = new JSONObject();
                out.put("ok", true);
                out.put("model", file.getName());
                out.put("bytes", file.length());
                return out.toString();
            } catch (Throwable t) {
                unloadLocked();
                return error("failed to load model: " + describe(t));
            }
        }
    }

    /** Release the engine and its native memory. Returns JSON. */
    public static String unload() {
        synchronized (LOCK) {
            unloadLocked();
            JSONObject out = new JSONObject();
            try {
                out.put("ok", true);
            } catch (Throwable t) {
                return error(describe(t));
            }
            return out.toString();
        }
    }

    /**
     * Generate a reply for a chat history.
     *
     * <p>Request JSON: {@code {"messages":[{"role","content"},...],
     * "max_tokens":N,"system":"..."}}. A fresh conversation is created per call
     * with the history as initial messages, so the Python side stays stateless.
     */
    public static String generate(String requestJson) {
        synchronized (LOCK) {
            Conversation conv = null;
            try {
                if (engine == null || !isLoaded()) {
                    return error("no model loaded");
                }
                JSONObject request = new JSONObject(requestJson);
                int maxTokens = request.optInt("max_tokens", 512);
                if (maxTokens <= 0) {
                    maxTokens = 512;
                }
                String system = request.optString("system", SYSTEM_PROMPT);
                if (system.isEmpty()) {
                    system = SYSTEM_PROMPT;
                }

                JSONArray messages = request.optJSONArray("messages");
                List<Message> history = new ArrayList<>();
                String prompt = "";
                int count = messages == null ? 0 : messages.length();
                for (int i = 0; i < count; i++) {
                    JSONObject m = messages.getJSONObject(i);
                    String role = m.optString("role", "user");
                    String content = m.optString("content", "");
                    if (i == count - 1 && "user".equals(role)) {
                        prompt = content;
                        continue;
                    }
                    if ("model".equals(role) || "assistant".equals(role)) {
                        history.add(Message.Companion.model(
                                Contents.Companion.of(content), null, null));
                    } else if ("system".equals(role)) {
                        history.add(Message.Companion.system(content));
                    } else {
                        history.add(Message.Companion.user(content));
                    }
                }
                if (prompt.isEmpty()) {
                    return error("no user message in request");
                }

                ConversationConfig config = new ConversationConfig(
                        Contents.Companion.of(system),          // systemInstruction
                        history,                                // initialMessages
                        null,                                   // tools
                        new SamplerConfig(40, 0.95, 0.8, 0),    // topK/topP/temp/seed
                        false,                                  // automaticToolCalling
                        null,                                   // channels
                        null,                                   // extraContext
                        null,                                   // loraConfig
                        true,                                   // prefillPrefaceOnInit
                        maxTokens,                              // maxOutputToken
                        null,                                   // thinkingConfig
                        false,                                  // enableResponseFormat
                        null,                                   // speculativeDecoding
                        null);                                  // chatTemplate

                conv = engine.createConversation(config);
                Message reply = conv.sendMessage(
                        Message.Companion.user(prompt),
                        null, null, null, null, maxTokens, null, null);
                String text = reply == null ? "" : reply.toString();
                if (text == null) {
                    text = "";
                }

                JSONObject out = new JSONObject();
                out.put("ok", true);
                out.put("text", text.trim());
                return out.toString();
            } catch (Throwable t) {
                return error("generation failed: " + describe(t));
            } finally {
                if (conv != null) {
                    try {
                        conv.close();
                    } catch (Throwable ignored) {
                        // release is best effort
                    }
                }
            }
        }
    }

    private static void unloadLocked() {
        if (conversation != null) {
            try {
                conversation.close();
            } catch (Throwable ignored) {
                // release is best effort
            }
            conversation = null;
        }
        if (engine != null) {
            try {
                engine.close();
            } catch (Throwable ignored) {
                // release is best effort
            }
            engine = null;
        }
        loadedPath = null;
    }

    private static long totalMemoryBytes() {
        try (BufferedReader reader = new BufferedReader(
                new FileReader("/proc/meminfo"))) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.startsWith("MemTotal:")) {
                    String digits = line.replaceAll("[^0-9]", "");
                    if (!digits.isEmpty()) {
                        return Long.parseLong(digits) * 1024L;
                    }
                }
            }
        } catch (Throwable ignored) {
            // fall through to the Java-heap estimate
        }
        return Runtime.getRuntime().maxMemory();
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

    /** Path of the currently loaded model file, or null. */
    public static String loadedPath() {
        synchronized (LOCK) {
            return loadedPath;
        }
    }
}
