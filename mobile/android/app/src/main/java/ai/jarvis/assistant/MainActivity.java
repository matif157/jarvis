package ai.jarvis.assistant;

import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

public class MainActivity extends Activity {
    private WebView webView;
    private Handler handler;
    private final int MAX_RETRIES = 20;
    private int retries = 0;

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
        loadWithRetry();
    }

    private void setupWebView() {
        webView = findViewById(R.id.webview);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(true);
        settings.setAllowContentAccess(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        settings.setUserAgentString(settings.getUserAgentString() + " JarvisAndroid/1.0.1");

        webView.setWebChromeClient(new WebChromeClient());
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return false;
            }

            @Override
            public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
                retryLoad();
            }

            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest request, android.webkit.WebResourceResponse errorResponse) {
                retryLoad();
            }
        });
    }

    private void startServer() {
        Thread serverThread = new Thread(() -> {
            try {
                Python py = Python.getInstance();
                py.getModule("run_server").callAttr("start", getFilesDir().getAbsolutePath());
            } catch (Exception e) {
                e.printStackTrace();
            }
        });
        serverThread.setDaemon(true);
        serverThread.start();
    }

    private void loadWithRetry() {
        if (retries >= MAX_RETRIES) {
            return;
        }
        handler.postDelayed(() -> {
            retries++;
            webView.loadUrl("http://127.0.0.1:8771/");
        }, 800 * retries);
    }

    private void retryLoad() {
        if (retries < MAX_RETRIES) {
            handler.postDelayed(() -> {
                retries++;
                webView.reload();
            }, 500 * retries);
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
