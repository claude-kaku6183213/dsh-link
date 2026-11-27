package app.dshlink;

import android.app.Activity;
import android.Manifest;
import android.app.AlertDialog;
import android.app.DownloadManager;
import android.content.ContentValues;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Environment;
import android.webkit.JavascriptInterface;
import android.webkit.URLUtil;
import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;
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
import android.widget.Toast;
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
    private volatile String lastErr = "";
    private volatile String lastLiveUrl = null;
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
        pass.setText("Change passphrase");
        pass.setOnClickListener(v -> askPassphrase(false));
        Button retry = new Button(this);
        retry.setText("Check now");
        retry.setOnClickListener(v -> pollNow());
        Button browser = new Button(this);
        browser.setText("Open in browser");
        browser.setOnClickListener(v -> {
            String u = lastLiveUrl != null ? lastLiveUrl : sp.getString("last_url", null);
            if (u == null) { Toast.makeText(this, "No link yet", Toast.LENGTH_SHORT).show(); return; }
            try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(u))); }
            catch (Exception e) { Toast.makeText(this, "No browser found", Toast.LENGTH_SHORT).show(); }
        });
        box.addView(titleTv);
        box.addView(hintTv);
        box.addView(retry);
        box.addView(browser);
        box.addView(pass);
        overlay = box;
        root.addView(overlay, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);
        web.setBackgroundColor(0xFF0B1020);
        if (Build.VERSION.SDK_INT <= 28 && checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.WRITE_EXTERNAL_STORAGE}, 7002);
        }
        loadKeyCache();
        String cached = sp.getString("last_url", null);
        if (sp.getString("pass", null) != null && cached != null) {
            loadHarness(cached, true);   // direct open; fresh link is checked in the background
        } else {
            showWaiting("Waiting for link…", "Looking for the latest link");
        }
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
                .setMessage("Enter the notebook's LINK_PASSPHRASE.")
                .setView(et)
                .setCancelable(!first)
                .setPositiveButton("Save", (d, w) -> {
                    String v = et.getText().toString().trim();
                    dialogOpen = false;
                    if (v.length() > 0) {
                        sp.edit().putString("pass", v).apply();
                        cachedKey = null;
                        cachedKeyId = "";
                        sp.edit().remove("key").remove("key_id").apply();
                        pollNow();
                    } else if (sp.getString("pass", null) == null) {
                        askPassphrase(true);
                    }
                })
                .setOnCancelListener(d -> dialogOpen = false);
        bd.show();
    }

    private void loadKeyCache() {
        String k = sp.getString("key", null);
        if (k != null) {
            try {
                cachedKey = Base64.decode(k, Base64.NO_WRAP);
                cachedKeyId = sp.getString("key_id", "");
            } catch (Exception e) {
                cachedKey = null;
                cachedKeyId = "";
            }
        }
    }

    private static String sha(String in) throws Exception {
        byte[] d = java.security.MessageDigest.getInstance("SHA-256").digest(in.getBytes(StandardCharsets.UTF_8));
        StringBuilder sb = new StringBuilder();
        for (byte b : d) sb.append(String.format("%02x", b));
        return sb.toString();
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
                if (r.isForMainFrame()) onMainFrameDead(e.getErrorCode() + " " + e.getDescription());
            }

            @Override
            public void onReceivedHttpError(WebView v, WebResourceRequest r, WebResourceResponse resp) {
                if (!r.isForMainFrame()) return;
                int c = resp.getStatusCode();
                if (c >= 500) onMainFrameDead("HTTP " + c);        // tunnel dead (Cloudflare 530/1033 etc.)
                else if (c == 401) { needFresh = true; pollNow(); } // token/cookie kho gaya -> fresh token URL
            }
        });

        web.addJavascriptInterface(new Bridge(), "DSHApp");
        web.setDownloadListener((url, ua, cd, mime, len) -> handleDownload(url, ua, cd, mime));

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

    // ------------------------------------------------------------------ downloads
    final class Bridge {
        @JavascriptInterface
        public void save(final String b64, final String mime, final String name) {
            new Thread(() -> {
                try {
                    byte[] data = Base64.decode(b64, Base64.DEFAULT);
                    String saved = saveToDownloads(name, mime, data);
                    toast("Saved to Downloads: " + saved);
                } catch (Throwable e) {
                    toast("Save failed: " + e.getMessage());
                }
            }).start();
        }

        @JavascriptInterface
        public void fail(final String msg) {
            toast("Download failed: " + msg);
        }
    }

    static final class MediaStoreDownloads {
        static Uri uri() {
            return android.provider.MediaStore.Downloads.EXTERNAL_CONTENT_URI;
        }
    }

    private void toast(final String m) {
        runOnUiThread(() -> Toast.makeText(MainActivity.this, m, Toast.LENGTH_LONG).show());
    }

    private static String cleanName(String n) {
        String x = (n == null || n.trim().isEmpty()) ? "download" : n.trim();
        return x.replaceAll("[\\\\/:*?\"<>|]", "_");
    }

    private String saveToDownloads(String name, String mime, byte[] data) throws Exception {
        String fn = cleanName(name);
        String mt = (mime == null || mime.isEmpty()) ? "application/octet-stream" : mime;
        if (Build.VERSION.SDK_INT >= 29) {
            ContentValues cv = new ContentValues();
            cv.put("_display_name", fn);
            cv.put("mime_type", mt);
            cv.put("relative_path", "Download/");
            Uri u = getContentResolver().insert(MediaStoreDownloads.uri(), cv);
            if (u == null) throw new Exception("could not create file");
            try (OutputStream os = getContentResolver().openOutputStream(u)) {
                os.write(data);
            }
            return fn;
        }
        File dir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
        dir.mkdirs();
        File f = new File(dir, fn);
        int i = 1;
        while (f.exists()) {
            int dot = fn.lastIndexOf('.');
            String n2 = dot > 0 ? fn.substring(0, dot) + " (" + i + ")" + fn.substring(dot) : fn + " (" + i + ")";
            f = new File(dir, n2);
            i++;
        }
        try (FileOutputStream os = new FileOutputStream(f)) {
            os.write(data);
        }
        return f.getName();
    }

    private void handleDownload(String url, String ua, String cd, String mime) {
        String name = cleanName(URLUtil.guessFileName(url, cd, mime));
        if (url.startsWith("blob:") || url.startsWith("data:")) {
            // blob/data URLs sirf page ke andar padhe ja sakte hain: JS se bytes nikalkar app ko do
            String esc = url.replace("\\", "\\\\").replace("'", "\\'");
            String nm = name.replace("\\", "\\\\").replace("'", "\\'");
            String js = "(function(){try{var x=new XMLHttpRequest();x.open('GET','" + esc + "',true);x.responseType='blob';"
                    + "x.onload=function(){var r=new FileReader();r.onloadend=function(){var d=String(r.result);"
                    + "DSHApp.save(d.substring(d.indexOf(',')+1),(x.response&&x.response.type)||'application/octet-stream','" + nm + "');};"
                    + "r.readAsDataURL(x.response);};x.onerror=function(){DSHApp.fail('could not read file');};x.send();}"
                    + "catch(e){DSHApp.fail(String(e));}})();";
            web.evaluateJavascript(js, null);
            toast("Preparing " + name + "…");
            return;
        }
        try {
            DownloadManager.Request rq = new DownloadManager.Request(Uri.parse(url));
            String ck = CookieManager.getInstance().getCookie(url);
            if (ck != null) rq.addRequestHeader("Cookie", ck);
            if (ua != null) rq.addRequestHeader("User-Agent", ua);
            if (mime != null && !mime.isEmpty()) rq.setMimeType(mime);
            rq.setTitle(name);
            rq.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            rq.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name);
            ((DownloadManager) getSystemService(DOWNLOAD_SERVICE)).enqueue(rq);
            toast("Downloading " + name);
        } catch (Exception e) {
            toast("Download failed: " + e.getMessage());
        }
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
        lastErr = why;
        showingWeb = false;
        showWaiting("Link is dead", currentHost + "\n" + why + "\nRetrying every few seconds");
        pollNow();
    }

    private void loadHarness(String url) {
        loadHarness(url, false);
    }

    private void loadHarness(String url, boolean quiet) {
        String host = Uri.parse(url).getHost();
        currentHost = host;
        lastLoadAt = System.currentTimeMillis();
        needFresh = false;
        if (host != null && !host.equals(failedHost)) failedHost = null;
        showingWeb = true;
        if (quiet) {
            overlay.setVisibility(View.GONE);
        } else {
            showWaiting("Opening Harness…", host == null ? "" : host);
            sp.edit().putString("last_url", url).apply();
        }
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
                showWaiting("Wrong passphrase", "Enter the correct passphrase (the notebook's LINK_PASSPHRASE)");
                askPassphrase(false);
                schedule(POLL_SLOW_MS);
                return;
            case NET:
                if (!showingWeb) showWaiting("Network issue", r.msg);
                next = POLL_FAST_MS;
                break;
            case EMPTY:
                if (!showingWeb) showWaiting("Waiting for link…", "No link has been published yet");
                break;
            case OK: {
                long age = System.currentTimeMillis() / 1000 - r.ts;
                boolean stale = age > STALE_S;
                boolean live = r.url.length() > 0 && !stale
                        && (r.status.equals("online") || r.status.equals("handoff") || r.status.equals("starting"));
                String host = hostOf(r.url);
                if (live) lastLiveUrl = r.url;
                if (!live) {
                    if (!showingWeb) {
                        showWaiting(stale && !r.status.equals("offline") ? "State is stale" : "Harness offline",
                                "Node " + r.node + " · " + r.status + " · opens as soon as a new link is published");
                    }
                    break;
                }
                if (!showingWeb) {
                    boolean sameFailed = host != null && host.equals(failedHost)
                            && System.currentTimeMillis() - failedAt < 4000;   // new tunnel hosts need a while for DNS: retry every ~5s
                    if (!sameFailed) loadHarness(r.url);
                    else showWaiting("Link is dead", host + "\n" + lastErr + "\nRetrying every few seconds");
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
        String id = sha(pass + "|" + salt + "|" + it);
        byte[] key = cachedKey;
        if (key == null || !id.equals(cachedKeyId)) {
            PBEKeySpec spec = new PBEKeySpec(pass.toCharArray(), salt.getBytes(StandardCharsets.UTF_8), it, 256);
            key = SecretKeyFactory.getInstance("PBKDF2withHmacSHA256").generateSecret(spec).getEncoded();
            cachedKey = key;
            cachedKeyId = id;
            sp.edit().putString("key", Base64.encodeToString(key, Base64.NO_WRAP)).putString("key_id", id).apply();
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
