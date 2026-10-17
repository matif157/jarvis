package ai.jarvis.assistant;

import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

public class MainActivity extends Activity {
    private static final String HOME_URL = "http://127.0.0.1:8771/";
    private static final int RETRY_DELAY_MS = 500;
    private static final int MAX_ATTEMPTS = 60;

    private WebView webView;
    private Handler handler;
    private int attempts = 0;
    private boolean loaded = false;
    private boolean loadScheduled = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        handler = new Handler(Looper.getMainLooper());

        if (!Python.isStarted()) {
            Python.start(new AndroidPlatform(this));
        }

        startServer();
        setupWebView();
        scheduleLoad();
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

            @Override
            public void onPageFinished(WebView view, String url) {
                // First successful load means the embedded server is up; stop retrying.
                loaded = true;
            }

            @Override
            public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
                // Server not ready yet — keep retrying until MAX_ATTEMPTS.
                if (!loaded) {
                    scheduleLoad();
                }
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

    private void scheduleLoad() {
        if (loaded || loadScheduled || attempts >= MAX_ATTEMPTS) {
            return;
        }
        loadScheduled = true;
        handler.postDelayed(() -> {
            loadScheduled = false;
            if (loaded || webView == null) {
                return;
            }
            attempts++;
            webView.loadUrl(HOME_URL);
            scheduleLoad();
        }, RETRY_DELAY_MS);
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
