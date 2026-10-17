package ai.jarvis.assistant;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.webkit.JavascriptInterface;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Map;

public class MainActivity extends Activity {
    private static final String HOME_URL = "http://127.0.0.1:8771/";
    private static final String HEALTH_URL = "http://127.0.0.1:8771/api/health";
    private static final int MAX_WAIT_MS = 180_000;
    private static final int POLL_INTERVAL_MS = 500;

    private static final int MIC_PERMISSION_REQUEST = 1001;

    private WebView webView;
    private static volatile MainActivity instance;

    private static final String LOADING_HTML =
            "<!DOCTYPE html><html><head><meta name=\"viewport\" "
            + "content=\"width=device-width, initial-scale=1\">"
            + "<style>body{font-family:sans-serif;display:flex;align-items:center;"
            + "justify-content:center;height:100vh;margin:0;background:#0f1115;color:#e8e8e8}"
            + "div{text-align:center;padding:20px}h1{font-weight:600;letter-spacing:2px}"
            + "p{color:#9aa0a6;font-size:14px}pre{color:#ff8a80;font-size:11px;text-align:left;"
            + "white-space:pre-wrap;word-break:break-word;max-width:90vw}</style></head>"
            + "<body><div><h1>JARVIS</h1><p id=\"s\">Starting local assistant\u2026</p>"
            + "<pre id=\"e\"></pre></div>"
            + "<script>var d=0;setInterval(function(){d++;var e=document.getElementById('s');"
            + "if(e)e.textContent='Starting local assistant\u2026 '+(d/2).toFixed(0)+'s';},500);"
            + "</script></body></html>";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        instance = this;
        try {
            ai.jarvis.assistant.voice.VoiceBridge.attach(getApplicationContext());
            ai.jarvis.assistant.voice.WakeBridge.attach(getApplicationContext());
        } catch (Throwable ignored) {
            // voice is optional: the app must start without it
        }

        try {
            if (!Python.isStarted()) {
                Python.start(new AndroidPlatform(this));
            }
        } catch (Throwable t) {
            showFatal("Python failed to start", t);
            return;
        }

        setupWebView();
        webView.loadDataWithBaseURL(HOME_URL, LOADING_HTML, "text/html", "utf-8", null);

        try {
            startServer();
        } catch (Throwable t) {
            showFatal("Server launch failed", t);
            return;
        }
        waitForServerThenLoad();
    }

    private void setupWebView() {
        webView = findViewById(R.id.webview);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(true);
        settings.setAllowContentAccess(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE);

        webView.addJavascriptInterface(new AndroidBridge(), "JarvisAndroid");

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                view.loadUrl(url);
                return true;
            }
        });
    }

    /** Called by WakeBridge when the wake word is detected. */
    public static void notifyWake(String keyword) {
        MainActivity activity = instance;
        if (activity == null) {
            return;
        }
        activity.runOnUiThread(() -> {
            if (activity.webView != null) {
                String payload = org.json.JSONObject.quote(keyword);
                activity.webView.evaluateJavascript(
                        "window.onJarvisWake&&window.onJarvisWake(" + payload + ")",
                        null);
            }
        });
    }

    /** Surface for page JS: {@code JarvisAndroid.requestMicPermission()}. */
    class AndroidBridge {
        @JavascriptInterface
        public void requestMicPermission() {
            runOnUiThread(() -> {
                if (checkSelfPermission(Manifest.permission.RECORD_AUDIO)
                        != PackageManager.PERMISSION_GRANTED) {
                    requestPermissions(
                            new String[]{Manifest.permission.RECORD_AUDIO},
                            MIC_PERMISSION_REQUEST);
                }
            });
        }

        @JavascriptInterface
        public boolean micPermissionGranted() {
            return checkSelfPermission(Manifest.permission.RECORD_AUDIO)
                    == PackageManager.PERMISSION_GRANTED;
        }
    }

    private void startServer() {
        new Thread(() -> {
            try {
                Python py = Python.getInstance();
                py.getModule("run_server").callAttr("start", getFilesDir().getAbsolutePath());
            } catch (Throwable t) {
                t.printStackTrace();
            }
        }).start();
    }

    private void waitForServerThenLoad() {
        new Thread(() -> {
            long deadline = System.currentTimeMillis() + MAX_WAIT_MS;
            while (System.currentTimeMillis() < deadline) {
                if (probeHealth()) {
                    runOnUiThread(() -> {
                        if (webView != null) {
                            webView.loadUrl(HOME_URL);
                        }
                    });
                    return;
                }
                if (isServerErrored()) {
                    break;
                }
                try {
                    Thread.sleep(POLL_INTERVAL_MS);
                } catch (InterruptedException e) {
                    return;
                }
            }
            runOnUiThread(this::showDiagnostics);
        }).start();
    }

    private boolean probeHealth() {
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL(HEALTH_URL).openConnection();
            conn.setConnectTimeout(1500);
            conn.setReadTimeout(1500);
            conn.setRequestMethod("GET");
            return conn.getResponseCode() == 200;
        } catch (Exception e) {
            return false;
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    private boolean isServerErrored() {
        try {
            Python py = Python.getInstance();
            Map<?, ?> status = (Map<?, ?>) py.getModule("run_server")
                    .callAttr("get_status").toJava(Object.class);
            Object err = status.get("error");
            return err != null && !err.toString().isEmpty();
        } catch (Throwable t) {
            return false;
        }
    }

    private void showDiagnostics() {
        if (webView == null) {
            return;
        }
        String err = "";
        try {
            Python py = Python.getInstance();
            Map<?, ?> status = (Map<?, ?>) py.getModule("run_server")
                    .callAttr("get_status").toJava(Object.class);
            Object e = status.get("error");
            if (e != null) {
                err = e.toString();
            }
        } catch (Throwable t) {
            err = String.valueOf(t);
        }
        if (err.isEmpty()) {
            err = "Server did not become ready within " + (MAX_WAIT_MS / 1000) + "s.";
        }
        String esc = err.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;");
        String html = "<!DOCTYPE html><html><head><meta name=\"viewport\" "
                + "content=\"width=device-width, initial-scale=1\"></head>"
                + "<body style=\"background:#0f1115;color:#e8e8e8;font-family:sans-serif;padding:16px\">"
                + "<h2>Jarvis could not start</h2><p style=\"color:#9aa0a6\">Diagnostics:</p>"
                + "<pre style=\"color:#ff8a80;font-size:11px;white-space:pre-wrap;word-break:break-word\">"
                + esc + "</pre></body></html>";
        webView.loadDataWithBaseURL(HOME_URL, html, "text/html", "utf-8", null);
    }

    private void showFatal(String title, Throwable t) {
        if (webView == null) {
            setupWebView();
        }
        StringBuilder sb = new StringBuilder(title).append("\n");
        sb.append(t.toString()).append("\n");
        for (StackTraceElement el : t.getStackTrace()) {
            sb.append("  at ").append(el.toString()).append("\n");
        }
        String esc = sb.toString().replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;");
        String html = "<!DOCTYPE html><html><body style=\"background:#0f1115;color:#e8e8e8;"
                + "font-family:sans-serif;padding:16px\"><h2>Jarvis error</h2>"
                + "<pre style=\"color:#ff8a80;font-size:11px;white-space:pre-wrap\">"
                + esc + "</pre></body></html>";
        webView.loadDataWithBaseURL(HOME_URL, html, "text/html", "utf-8", null);
    }

    @Override
    public void onBackPressed() {
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
