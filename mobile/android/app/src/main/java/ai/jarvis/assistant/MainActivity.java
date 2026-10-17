package ai.jarvis.assistant;

import android.app.Activity;
import android.os.Bundle;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.net.HttpURLConnection;
import java.net.URL;

public class MainActivity extends Activity {
    private static final String HOME_URL = "http://127.0.0.1:8771/";
    private static final String HEALTH_URL = "http://127.0.0.1:8771/api/health";
    private static final int MAX_WAIT_MS = 180_000;
    private static final int POLL_INTERVAL_MS = 500;

    private WebView webView;

    private static final String LOADING_HTML =
            "<!DOCTYPE html><html><head><meta name=\"viewport\" "
            + "content=\"width=device-width, initial-scale=1\">"
            + "<style>body{font-family:sans-serif;display:flex;align-items:center;"
            + "justify-content:center;height:100vh;margin:0;background:#0f1115;color:#e8e8e8}"
            + "div{text-align:center}h1{font-weight:600;letter-spacing:2px}"
            + "p{color:#9aa0a6;font-size:14px}</style></head>"
            + "<body><div><h1>JARVIS</h1><p id=\"s\">Starting local assistant\u2026</p></div>"
            + "<script>var d=0;setInterval(function(){d++;document.getElementById('s')"
            + ".textContent='Starting local assistant\u2026 '+(d/2).toFixed(0)+'s';},500);"
            + "</script></body></html>";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        if (!Python.isStarted()) {
            Python.start(new AndroidPlatform(this));
        }

        setupWebView();
        webView.loadDataWithBaseURL(HOME_URL, LOADING_HTML, "text/html", "utf-8", null);

        startServer();
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

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                view.loadUrl(url);
                return true;
            }
        });
    }

    private void startServer() {
        new Thread(() -> {
            try {
                Python py = Python.getInstance();
                py.getModule("run_server").callAttr("start", getFilesDir().getAbsolutePath());
            } catch (Exception e) {
                e.printStackTrace();
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
                try {
                    Thread.sleep(POLL_INTERVAL_MS);
                } catch (InterruptedException e) {
                    return;
                }
            }
        }).start();
    }

    private boolean probeHealth() {
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL(HEALTH_URL).openConnection();
            conn.setConnectTimeout(1500);
            conn.setReadTimeout(1500);
            conn.setRequestMethod("GET");
            int code = conn.getResponseCode();
            return code == 200;
        } catch (Exception e) {
            return false;
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
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
