package ai.jarvis.assistant.device;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.content.Intent;
import android.graphics.Path;
import android.graphics.Rect;
import android.os.Build;
import android.os.Bundle;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Locale;

/**
 * Accessibility service behind device control (Phase 24).
 *
 * <p>The user grants this service themselves in Android Settings >
 * Accessibility - the app only ever opens that screen, it never enables
 * itself. Consent for individual calls is enforced in Python
 * ({@code device.enabled}); this class reports what actually happened.
 *
 * <p>Every public method returns JSON in / JSON out like the voice and
 * WhatsApp bridges, and fails honestly with a specific message when the
 * service is off, there is no active window, or the target refused the
 * action.
 */
public class DeviceControlService extends AccessibilityService {

    static final String NOT_RUNNING =
            "accessibility service not running - enable Jarvis under Android Settings > Accessibility";

    private static final int SCREEN_MIN = 100;
    private static final int SCREEN_MAX = 8000;
    private static final int NODES_MAX = 300;
    private static final int TEXT_MAX = 2000;

    private static volatile DeviceControlService instance;

    @Override
    public void onServiceConnected() {
        super.onServiceConnected();
        instance = this;
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        // window state only: events are used to keep the service alive, never logged
    }

    @Override
    public void onInterrupt() {
    }

    @Override
    public boolean onUnbind(Intent intent) {
        instance = null;
        return super.onUnbind(intent);
    }

    static boolean isRunning() {
        return instance != null;
    }

    /** Foreground package name, "" when the service is off or unreadable. */
    static String foregroundPackage() {
        DeviceControlService svc = instance;
        if (svc == null) {
            return "";
        }
        AccessibilityNodeInfo root = svc.getRootInActiveWindow();
        if (root == null) {
            return "";
        }
        CharSequence pkg = root.getPackageName();
        return pkg == null ? "" : pkg.toString();
    }

    /** back / home / recents / notifications / quick_settings / lock. */
    static String globalAction(String name) {
        DeviceControlService svc = instance;
        if (svc == null) {
            return error(NOT_RUNNING);
        }
        int action;
        switch (name) {
            case "back":
                action = GLOBAL_ACTION_BACK;
                break;
            case "home":
                action = GLOBAL_ACTION_HOME;
                break;
            case "recents":
                action = GLOBAL_ACTION_RECENTS;
                break;
            case "notifications":
                action = GLOBAL_ACTION_NOTIFICATIONS;
                break;
            case "quick_settings":
                action = GLOBAL_ACTION_QUICK_SETTINGS;
                break;
            case "lock":
                if (Build.VERSION.SDK_INT < 28) {
                    return error("lock needs Android 9+");
                }
                action = GLOBAL_ACTION_LOCK_SCREEN;
                break;
            default:
                return error("unknown global action: " + name);
        }
        try {
            boolean ok = svc.performGlobalAction(action);
            JSONObject out = new JSONObject();
            out.put("ok", ok);
            out.put("action", name);
            if (!ok) {
                out.put("error", "global action '" + name + "' was refused");
            }
            return out.toString();
        } catch (Throwable t) {
            return error(describe(t));
        }
    }

    /** Visible text of the active window, bounded to maxChars (clamped). */
    static String screenText(int maxChars) {
        DeviceControlService svc = instance;
        if (svc == null) {
            return error(NOT_RUNNING);
        }
        int limit = Math.max(SCREEN_MIN, Math.min(maxChars, SCREEN_MAX));
        AccessibilityNodeInfo root = svc.getRootInActiveWindow();
        if (root == null) {
            return error("no active window to read");
        }
        try {
            StringBuilder sb = new StringBuilder();
            String previous = null;
            Deque<AccessibilityNodeInfo> queue = new ArrayDeque<>();
            queue.add(root);
            boolean truncated = false;
            while (!queue.isEmpty()) {
                AccessibilityNodeInfo node = queue.poll();
                previous = appendLine(sb, node.getText(), previous, limit);
                previous = appendLine(sb, node.getContentDescription(), previous, limit);
                if (sb.length() >= limit) {
                    truncated = !queue.isEmpty();
                    break;
                }
                for (int i = 0; i < node.getChildCount(); i++) {
                    AccessibilityNodeInfo child = node.getChild(i);
                    if (child != null) {
                        queue.add(child);
                    }
                }
            }
            JSONObject out = new JSONObject();
            out.put("ok", true);
            out.put("text", sb.toString().trim());
            out.put("package", packageName(root));
            out.put("truncated", truncated);
            return out.toString();
        } catch (Throwable t) {
            return error(describe(t));
        }
    }

    /**
     * Actionable nodes in stable BFS order: index, kind flags (click/edit/scroll),
     * label and screen bounds. The same order is used by clickNode().
     */
    static String actionableNodes(int maxNodes) {
        DeviceControlService svc = instance;
        if (svc == null) {
            return error(NOT_RUNNING);
        }
        int limit = Math.max(1, Math.min(maxNodes, NODES_MAX));
        AccessibilityNodeInfo root = svc.getRootInActiveWindow();
        if (root == null) {
            return error("no active window to inspect");
        }
        try {
            JSONArray nodes = new JSONArray();
            boolean more = false;
            int index = 0;
            Deque<AccessibilityNodeInfo> queue = new ArrayDeque<>();
            queue.add(root);
            while (!queue.isEmpty() && !more) {
                AccessibilityNodeInfo node = queue.poll();
                if (node.isClickable() || node.isEditable() || node.isScrollable()) {
                    if (index >= limit) {
                        more = true;
                    } else {
                        nodes.put(nodeJson(node, index));
                        index++;
                    }
                }
                for (int i = 0; i < node.getChildCount(); i++) {
                    AccessibilityNodeInfo child = node.getChild(i);
                    if (child != null) {
                        queue.add(child);
                    }
                }
            }
            JSONObject out = new JSONObject();
            out.put("ok", true);
            out.put("package", packageName(root));
            out.put("count", nodes.length());
            out.put("more", more);
            out.put("nodes", nodes);
            return out.toString();
        } catch (Throwable t) {
            return error(describe(t));
        }
    }

    /** ACTION_CLICK on the node that held this index in the last listing order. */
    static String clickNode(int index) {
        DeviceControlService svc = instance;
        if (svc == null) {
            return error(NOT_RUNNING);
        }
        if (index < 0) {
            return error("node index must be >= 0");
        }
        AccessibilityNodeInfo root = svc.getRootInActiveWindow();
        if (root == null) {
            return error("no active window to tap");
        }
        try {
            int seen = 0;
            Deque<AccessibilityNodeInfo> queue = new ArrayDeque<>();
            queue.add(root);
            while (!queue.isEmpty()) {
                AccessibilityNodeInfo node = queue.poll();
                if (node.isClickable() || node.isEditable() || node.isScrollable()) {
                    if (seen == index) {
                        if (node.isClickable()) {
                            boolean ok = node.performAction(AccessibilityNodeInfo.ACTION_CLICK);
                            return ok
                                    ? okJson("index", index)
                                    : error("node " + index + " refused the click - use device.tap instead");
                        }
                        return error("node " + index + " is not clickable - use device.tap or device.scroll");
                    }
                    seen++;
                }
                for (int i = 0; i < node.getChildCount(); i++) {
                    AccessibilityNodeInfo child = node.getChild(i);
                    if (child != null) {
                        queue.add(child);
                    }
                }
            }
            return error("no node at index " + index + "- list device.nodes again");
        } catch (Throwable t) {
            return error(describe(t));
        }
    }

    /** Tap at screen pixel coordinates through a system gesture. */
    static String tap(float x, float y) {
        DeviceControlService svc = instance;
        if (svc == null) {
            return error(NOT_RUNNING);
        }
        if (x < 0 || y < 0) {
            return error("tap requires x and y >= 0");
        }
        Path path = new Path();
        path.moveTo(x, y);
        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(new GestureDescription.StrokeDescription(path, 0, 80))
                .build();
        return dispatch(svc, gesture, "tap at " + (int) x + "," + (int) y);
    }

    /** Swipe from the screen center: direction is where the content moves. */
    static String scroll(String direction) {
        DeviceControlService svc = instance;
        if (svc == null) {
            return error(NOT_RUNNING);
        }
        AccessibilityNodeInfo root = svc.getRootInActiveWindow();
        if (root == null) {
            return error("no active window to scroll");
        }
        Rect rect = new Rect();
        root.getBoundsInScreen(rect);
        if (rect.width() <= 0 || rect.height() <= 0) {
            return error("cannot measure the screen");
        }
        int cx = rect.centerX();
        int cy = rect.centerY();
        int dist = Math.max(60, Math.min(Math.min(rect.width(), rect.height()) / 3, 600));
        Path path = new Path();
        switch (direction == null ? "" : direction.toLowerCase(Locale.ROOT)) {
            case "down":
                path.moveTo(cx, cy + dist);
                path.lineTo(cx, cy - dist);
                break;
            case "up":
                path.moveTo(cx, cy - dist);
                path.lineTo(cx, cy + dist);
                break;
            case "left":
                path.moveTo(cx + dist, cy);
                path.lineTo(cx - dist, cy);
                break;
            case "right":
                path.moveTo(cx - dist, cy);
                path.lineTo(cx + dist, cy);
                break;
            default:
                return error("unknown scroll direction: " + direction);
        }
        GestureDescription gesture = new GestureDescription.Builder()
                .addStroke(new GestureDescription.StrokeDescription(path, 0, 300))
                .build();
        return dispatch(svc, gesture, "scroll " + direction);
    }

    /**
     * Replace the focused editable field's content (ACTION_SET_TEXT has no
     * insert mode - the message says so honestly when no field is focused).
     */
    static String setText(String text) {
        DeviceControlService svc = instance;
        if (svc == null) {
            return error(NOT_RUNNING);
        }
        if (text == null || text.trim().isEmpty()) {
            return error("type requires non-empty text");
        }
        if (text.length() > TEXT_MAX) {
            return error("type text is limited to " + TEXT_MAX + " characters");
        }
        AccessibilityNodeInfo root = svc.getRootInActiveWindow();
        if (root == null) {
            return error("no active window to type into");
        }
        try {
            AccessibilityNodeInfo target = root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY);
            if (target == null || !target.isEditable()) {
                target = null;
                Deque<AccessibilityNodeInfo> queue = new ArrayDeque<>();
                queue.add(root);
                while (!queue.isEmpty()) {
                    AccessibilityNodeInfo node = queue.poll();
                    if (node.isEditable() && node.isFocused()) {
                        target = node;
                        break;
                    }
                    for (int i = 0; i < node.getChildCount(); i++) {
                        AccessibilityNodeInfo child = node.getChild(i);
                        if (child != null) {
                            queue.add(child);
                        }
                    }
                }
            }
            if (target == null) {
                return error("no focused text field - tap one first");
            }
            Bundle args = new Bundle();
            args.putCharSequence(
                    AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text);
            boolean ok = target.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args);
            if (!ok) {
                return error("the focused field refused the text");
            }
            JSONObject out = new JSONObject();
            out.put("ok", true);
            out.put("chars", text.length());
            return out.toString();
        } catch (Throwable t) {
            return error(describe(t));
        }
    }

    // ------------------------------------------------------------------
    // helpers
    // ------------------------------------------------------------------
    private static String dispatch(DeviceControlService svc, GestureDescription gesture,
                                   String what) {
        try {
            boolean accepted = svc.dispatchGesture(gesture, null, null);
            if (!accepted) {
                return error("gesture was not accepted (" + what + ")");
            }
            JSONObject out = new JSONObject();
            out.put("ok", true);
            out.put("action", what);
            return out.toString();
        } catch (Throwable t) {
            return error(describe(t));
        }
    }

    private static JSONObject nodeJson(AccessibilityNodeInfo node, int index) throws Exception {
        JSONObject item = new JSONObject();
        item.put("index", index);
        StringBuilder kind = new StringBuilder();
        if (node.isClickable()) {
            kind.append("click");
        }
        if (node.isEditable()) {
            if (kind.length() > 0) {
                kind.append(",");
            }
            kind.append("edit");
        }
        if (node.isScrollable()) {
            if (kind.length() > 0) {
                kind.append(",");
            }
            kind.append("scroll");
        }
        item.put("kind", kind.toString());
        String label = "";
        CharSequence text = node.getText();
        if (text == null || text.length() == 0) {
            text = node.getContentDescription();
        }
        if (text != null && text.length() > 0) {
            label = text.toString().replace('\n', ' ').trim();
            if (label.length() > 60) {
                label = label.substring(0, 60);
            }
        }
        item.put("label", label);
        Rect rect = new Rect();
        node.getBoundsInScreen(rect);
        JSONObject bounds = new JSONObject();
        bounds.put("l", rect.left);
        bounds.put("t", rect.top);
        bounds.put("r", rect.right);
        bounds.put("b", rect.bottom);
        item.put("bounds", bounds);
        return item;
    }

    /** Append one text segment on its own line, skipping repeats, bounded by limit. */
    private static String appendLine(StringBuilder sb, CharSequence value, String previous,
                                     int limit) {
        if (value == null) {
            return previous;
        }
        String line = value.toString().replace('\n', ' ').trim();
        if (line.isEmpty() || line.equals(previous)) {
            return previous;
        }
        if (sb.length() > 0) {
            sb.append('\n');
        }
        sb.append(line);
        if (sb.length() > limit) {
            sb.setLength(limit);
        }
        return line;
    }

    private static String packageName(AccessibilityNodeInfo root) {
        CharSequence pkg = root.getPackageName();
        return pkg == null ? "" : pkg.toString();
    }

    private static String okJson(String key, int value) {
        try {
            JSONObject out = new JSONObject();
            out.put("ok", true);
            out.put(key, value);
            return out.toString();
        } catch (Throwable t) {
            return "{\"ok\":true}";
        }
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
