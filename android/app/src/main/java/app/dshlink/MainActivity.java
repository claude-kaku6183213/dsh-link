package app.dshlink;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.util.Base64;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import javax.crypto.BadPaddingException;
import javax.crypto.Cipher;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.PBEKeySpec;
import javax.crypto.spec.SecretKeySpec;

/**
 * DSH: fullscreen launcher + Harness WebView. Latest tunnel link Supabase se leta hai (AES-GCM decrypt),
 * Harness ko app ke andar kholta hai (address bar nahi), aur link badalne/dead hone par khud naya dhundh leta hai.
 */
public class MainActivity extends Activity {
    // Public values (launcher ki config.js jaisi). Passphrase app me daali jati hai, yahan nahi.
    static final String SUPA = "https://lofqgjdfemxkfxpserin.supabase.co";
    static final String ANON = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxvZnFnamRmZW14a2Z4cHNlcmluIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTQ4MDk2MTQsImV4cCI6MjExMDM4NTYxNH0.fypvhatoxrHY8rzRGPHblkSJBgIv_JxwEmFRF5U9YeQ";
    static final long STALE_S = 25 * 60;
    static final long POLL_FAST_MS = 5000;
    static final long POLL_SLOW_MS = 30000;
    static final int FILE_REQ = 7001;

    enum Kind { OK, NO_PASS, BAD_PASS, NET, EMPTY }

    static class Result {
        Kind kind;
        String msg = "";
        String status = "";
        String node = "";
        String url = "";
        long ts = 0;
        Result(Kind k) { kind = k; }
    }

    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private SharedPreferences sp;
    private WebView web;
    private View overlay;
    private TextView titleTv;
    private TextView hintTv;
    private ValueCallback<Uri[]> fileCb;

    private volatile boolean showingWeb = false;
    private volatile String currentHost = null;
    private volatile String failedHost = null;
    private volatile long failedAt = 0;
    private volatile long lastLoadAt = 0;
    private volatile boolean needFresh = false;
    private boolean polling = false;
    private boolean dialogOpen = false;
    private byte[] cachedKey;
    private String cachedKeyId = "";

    private final Runnable pollTask = new Runnable() {
        @Override public void run() { pollOnce(); }
    };

    // ------------------------------------------------------------------ lifecycle / UI
    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        sp = getSharedPreferences("dsh", MODE_PRIVATE);
        getWindow().setStatusBarColor(0xFF0B1020);
        getWindow().setNavigationBarColor(0xFF0B1020);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(0xFF0B1020);

        web = new WebView(this);
        setupWebView();
        root.addView(web, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER);
        box.setBackgroundColor(0xFF0B1020);
        box.setPadding(dp(28), dp(28), dp(28), dp(28));
        titleTv = new TextView(this);
        titleTv.setTextColor(Color.WHITE);
        titleTv.setTextSize(22);
        titleTv.setGravity(Gravity.CENTER);
        titleTv.setText("DSH");
        hintTv = new TextView(this);
        hintTv.setTextColor(0xFF9AA4BF);
        hintTv.setTextSize(14);
        hintTv.setGravity(Gravity.CENTER);
        hintTv.setPadding(0, dp(12), 0, dp(20));
        Button pass = new Button(this);
        pass.setText("Passphrase badlo");
        pass.setOnClickListener(v -> askPassphrase(false));
        Button retry = new Button(this);
        retry.setText("Abhi check karo");
        retry.setOnClickListener(v -> pollNow());
        box.addView(titleTv);
        box.addView(hintTv);
        box.addView(retry);
        box.addView(pass);
        overlay = box;
        root.addView(overlay, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);
        showWaiting("Link ka intezaar…", "Latest link dhundh raha hoon");
    }

    private int dp(int v) {
        return (int) (v * getResources().getDisplayMetrics().density);
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (sp.getString("pass", null) == null) {
            askPassphrase(true);
        } else {
            pollNow();
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        ui.removeCallbacks(pollTask);
        polling = false;
    }

    @Override
    protected void onDestroy() {
        ui.removeCallbacksAndMessages(null);
        io.shutdownNow();
        if (web != null) web.destroy();
        super.onDestroy();
    }

    @Override
    public void onBackPressed() {
        if (showingWeb && web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    private void showWaiting(String title, String hint) {
        ui.post(() -> {
            titleTv.setText(title);
            hintTv.setText(hint);
            overlay.setVisibility(View.VISIBLE);
        });
    }

    private void askPassphrase(boolean first) {
        if (dialogOpen) return;
        dialogOpen = true;
        final EditText et = new EditText(this);
        et.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        et.setHint("LINK_PASSPHRASE");
        AlertDialog.Builder bd = new AlertDialog.Builder(this)
                .setTitle("Passphrase")
                .setMessage("Notebook ke LINK_PASSPHRASE wali passphrase daalo.")
                .setView(et)
                .setCancelable(!first)
                .setPositiveButton("Save", (d, w) -> {
                    String v = et.getText().toString().trim();
                    dialogOpen = false;
                    if (v.length() > 0) {
                        sp.edit().putString("pass", v).apply();
                        cachedKey = null;
                        cachedKeyId = "";
                        pollNow();
                    } else if (sp.getString("pass", null) == null) {
                        askPassphrase(true);
                    }
                })
                .setOnCancelListener(d -> dialogOpen = false);
        bd.show();
    }

    // ------------------------------------------------------------------ WebView
    private void setupWebView() {
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setSupportZoom(false);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        CookieManager cm = CookieManager.getInstance();
        cm.setAcceptCookie(true);
        cm.setAcceptThirdPartyCookies(web, true);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                Uri u = r.getUrl();
                String h = u.getHost();
                if (h != null && h.equals(currentHost)) return false;
                if ("http".equals(u.getScheme()) || "https".equals(u.getScheme())) {
                    try { startActivity(new Intent(Intent.ACTION_VIEW, u)); } catch (Exception ignored) { }
                    return true;
                }
                return false;
            }

            @Override
            public void onPageFinished(WebView v, String url) {
                if (showingWeb && failedHost == null) overlay.setVisibility(View.GONE);
            }

            @Override
            public void onReceivedError(WebView v, WebResourceRequest r, WebResourceError e) {
                if (r.isForMainFrame()) onMainFrameDead("error");
            }

            @Override
            public void onReceivedHttpError(WebView v, WebResourceRequest r, WebResourceResponse resp) {
                if (!r.isForMainFrame()) return;
                int c = resp.getStatusCode();
                if (c >= 500) onMainFrameDead("HTTP " + c);        // tunnel dead (Cloudflare 530/1033 etc.)
                else if (c == 401) { needFresh = true; pollNow(); } // token/cookie kho gaya -> fresh token URL
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> cb, FileChooserParams p) {
                if (fileCb != null) fileCb.onReceiveValue(null);
                fileCb = cb;
                try {
                    startActivityForResult(p.createIntent(), FILE_REQ);
                } catch (Exception e) {
                    fileCb = null;
                    return false;
                }
                return true;
            }
        });
    }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        if (req == FILE_REQ && fileCb != null) {
            fileCb.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(res, data));
            fileCb = null;
            return;
        }
        super.onActivityResult(req, res, data);
    }

    private void onMainFrameDead(String why) {
        failedHost = currentHost;
        failedAt = System.currentTimeMillis();
        showingWeb = false;
        showWaiting("Link dead hai", "Naya link dhundh raha hoon (" + why + ")");
        pollNow();
    }

    private void loadHarness(String url) {
        String host = Uri.parse(url).getHost();
        currentHost = host;
        lastLoadAt = System.currentTimeMillis();
        needFresh = false;
        if (host != null && !host.equals(failedHost)) failedHost = null;
        showingWeb = true;
        showWaiting("Harness khul raha hai…", host == null ? "" : host);
        web.loadUrl(url);
    }

    // ------------------------------------------------------------------ polling
    private void pollNow() {
        ui.removeCallbacks(pollTask);
        polling = true;
        ui.post(pollTask);
    }

    private void schedule(long ms) {
        if (!polling) return;
        ui.removeCallbacks(pollTask);
        ui.postDelayed(pollTask, ms);
    }

    private void pollOnce() {
        if (io.isShutdown()) return;
        io.execute(() -> {
            final Result r = fetch();
            boolean dead = false;
            if (r.kind == Kind.OK && showingWeb && r.url.length() > 0) {
                String host = hostOf(r.url);
                if (host != null && !host.equals(currentHost)) dead = !alive(currentHost);
            }
            final boolean currentDead = dead;
            ui.post(() -> handle(r, currentDead));
        });
    }

    private void handle(Result r, boolean currentDead) {
        long next = POLL_FAST_MS;
        switch (r.kind) {
            case NO_PASS:
                askPassphrase(true);
                return;
            case BAD_PASS:
                showWaiting("Passphrase galat hai", "Sahi passphrase daalo (notebook ka LINK_PASSPHRASE)");
                askPassphrase(false);
                schedule(POLL_SLOW_MS);
                return;
            case NET:
                if (!showingWeb) showWaiting("Network issue", r.msg);
                next = POLL_FAST_MS;
                break;
            case EMPTY:
                if (!showingWeb) showWaiting("Link ka intezaar…", "Abhi koi link publish nahi hua");
                break;
            case OK: {
                long age = System.currentTimeMillis() / 1000 - r.ts;
                boolean stale = age > STALE_S;
                boolean live = r.url.length() > 0 && !stale
                        && (r.status.equals("online") || r.status.equals("handoff") || r.status.equals("starting"));
                String host = hostOf(r.url);
                if (!live) {
                    if (!showingWeb) {
                        showWaiting(stale && !r.status.equals("offline") ? "State purana hai" : "Harness offline",
                                "Node " + r.node + " · " + r.status + " · naya link aate hi khul jayega");
                    }
                    break;
                }
                if (!showingWeb) {
                    boolean sameFailed = host != null && host.equals(failedHost)
                            && System.currentTimeMillis() - failedAt < 60000;
                    if (!sameFailed) loadHarness(r.url);
                    else showWaiting("Link dead hai", "Naya link ka intezaar…");
                } else if (needFresh && System.currentTimeMillis() - lastLoadAt > 15000) {
                    loadHarness(r.url);
                } else if (host != null && !host.equals(currentHost) && currentDead) {
                    loadHarness(r.url);
                }
                break;
            }
        }
        schedule(showingWeb && overlay.getVisibility() != View.VISIBLE ? POLL_SLOW_MS : next);
    }

    private static String hostOf(String url) {
        try { return Uri.parse(url).getHost(); } catch (Exception e) { return null; }
    }

    private boolean alive(String host) {
        if (host == null) return false;
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL("https://" + host + "/").openConnection();
            c.setConnectTimeout(8000);
            c.setReadTimeout(8000);
            c.setInstanceFollowRedirects(false);
            int code = c.getResponseCode();
            return code < 500;
        } catch (Exception e) {
            return false;
        } finally {
            if (c != null) c.disconnect();
        }
    }

    // ------------------------------------------------------------------ Supabase + decrypt
    private Result fetch() {
        String pass = sp.getString("pass", null);
        if (pass == null) return new Result(Kind.NO_PASS);
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(SUPA + "/rest/v1/launch_state?id=eq.1&select=enc").openConnection();
            c.setConnectTimeout(10000);
            c.setReadTimeout(10000);
            c.setRequestProperty("apikey", ANON);
            c.setRequestProperty("Authorization", "Bearer " + ANON);
            c.setRequestProperty("Accept", "application/json");
            int code = c.getResponseCode();
            if (code != 200) {
                Result r = new Result(Kind.NET);
                r.msg = "Supabase HTTP " + code;
                return r;
            }
            JSONArray arr = new JSONArray(readAll(c.getInputStream()));
            if (arr.length() == 0) return new Result(Kind.EMPTY);
            Object e = arr.getJSONObject(0).opt("enc");
            if (e == null || e == JSONObject.NULL) return new Result(Kind.EMPTY);
            JSONObject env = (e instanceof JSONObject) ? (JSONObject) e : new JSONObject(e.toString());
            if (!env.has("ct")) return new Result(Kind.EMPTY);
            String plain;
            try {
                plain = decrypt(env, pass);
            } catch (BadPaddingException bp) {
                return new Result(Kind.BAD_PASS);
            }
            JSONObject p = new JSONObject(plain);
            Result r = new Result(Kind.OK);
            r.status = p.optString("status", "");
            r.node = p.optString("node", "");
            r.url = p.optString("url", "");
            r.ts = p.optLong("ts", 0);
            return r;
        } catch (Exception ex) {
            Result r = new Result(Kind.NET);
            r.msg = ex.getClass().getSimpleName() + ": " + String.valueOf(ex.getMessage());
            return r;
        } finally {
            if (c != null) c.disconnect();
        }
    }

    private String decrypt(JSONObject env, String pass) throws Exception {
        String salt = env.optString("salt", "dsh-link-v1");
        int it = env.optInt("it", 200000);
        String id = pass + "|" + salt + "|" + it;
        byte[] key = cachedKey;
        if (key == null || !id.equals(cachedKeyId)) {
            PBEKeySpec spec = new PBEKeySpec(pass.toCharArray(), salt.getBytes(StandardCharsets.UTF_8), it, 256);
            key = SecretKeyFactory.getInstance("PBKDF2withHmacSHA256").generateSecret(spec).getEncoded();
            cachedKey = key;
            cachedKeyId = id;
        }
        byte[] iv = Base64.decode(env.getString("iv"), Base64.DEFAULT);
        byte[] ct = Base64.decode(env.getString("ct"), Base64.DEFAULT);
        Cipher ci = Cipher.getInstance("AES/GCM/NoPadding");
        ci.init(Cipher.DECRYPT_MODE, new SecretKeySpec(key, "AES"), new GCMParameterSpec(128, iv));
        return new String(ci.doFinal(ct), StandardCharsets.UTF_8);
    }

    private static String readAll(InputStream in) throws Exception {
        ByteArrayOutputStream bo = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) > 0) bo.write(buf, 0, n);
        return new String(bo.toByteArray(), StandardCharsets.UTF_8);
    }
}
