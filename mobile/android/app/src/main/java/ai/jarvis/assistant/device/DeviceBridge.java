package ai.jarvis.assistant.device;

import org.json.JSONObject;

import java.util.Locale;

/**
 * Action bridge for device control (Phase 24).
 *
 * <p>Python sends {@code {"action": "back" | "screen" | "tap" | ...}} and
 * gets JSON back, like the voice and WhatsApp bridges. It holds no state
 * and needs no app context: everything lives in
 * {@link DeviceControlService}, which only exists once the user has
 * granted the service in Android Settings > Accessibility. The in-app
 * half of consent ({@code device.enabled}) and the audit log are enforced
 * in Python before this class is ever called.
 */
public final class DeviceBridge {

    private DeviceBridge() {
    }

    /**
     * {ok, supported, running, foreground} - consumed by
     * {@code GET /api/device/status}. Never gated: the user needs this
     * report to grant consent.
     */
    public static String status() {
        JSONObject out = new JSONObject();
        try {
            out.put("ok", true);
            out.put("supported", true);
            out.put("running", DeviceControlService.isRunning());
            out.put("foreground", DeviceControlService.foregroundPackage());
        } catch (Throwable t) {
            return error(describe(t));
        }
        return out.toString();
    }

    /**
     * {"action": ..., ...} -> {ok, ...} / error. One dispatch point so the
     * action whitelist stays in exactly one place (Python validates first,
     * this switch is the second gate).
     */
    public static String action(String requestJson) {
        try {
            JSONObject request = new JSONObject(
                    requestJson == null || requestJson.isEmpty() ? "{}" : requestJson);
            String action = request.optString("action", "").trim().toLowerCase(Locale.ROOT);
            if (action.isEmpty()) {
                return error("action is required");
            }
            if (!DeviceControlService.isRunning()) {
                return error(DeviceControlService.NOT_RUNNING);
            }
            switch (action) {
                case "back":
                case "home":
                case "recents":
                case "notifications":
                case "quick_settings":
                case "lock":
                    return DeviceControlService.globalAction(action);
                case "screen":
                    return DeviceControlService.screenText(request.optInt("max_chars", 4000));
                case "nodes":
                    return DeviceControlService.actionableNodes(request.optInt("max_nodes", 200));
                case "tap":
                    return DeviceControlService.tap(
                            (float) request.optDouble("x", -1),
                            (float) request.optDouble("y", -1));
                case "click_node":
                    return DeviceControlService.clickNode(request.optInt("index", -1));
                case "scroll":
                    return DeviceControlService.scroll(request.optString("direction", ""));
                case "type":
                    return DeviceControlService.setText(request.optString("text", ""));
                default:
                    return error("unknown device action: " + action);
            }
        } catch (Throwable t) {
            return error(describe(t));
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
