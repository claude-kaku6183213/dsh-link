# DSH Link — Kaggle DSH harness ka apna launcher

Ek chhota **GitHub Pages PWA** jo tumhare 24/7 Kaggle DSH harness ka **latest tunnel link khud dhundh leta hai**.
Har restart/handoff ke baad naya `https://xxxx.trycloudflare.com/?token=…` link kholne ki zarurat nahi — phone pe app icon kholo → **Open Harness** (auto-open on rakho to khud khul jayega).

```
Kaggle notebook A/B
   publish("online"|"handoff") / renewer() / shutdown()
        │  AES-GCM (PBKDF2-SHA256, 200k) encrypted envelope
        ├──────────────► Supabase table launch_state   (PRIMARY — uncached, ~0.2s)
        ├──────────────► HTTP endpoint (Cloudflare Worker, optional)
        └──────────────► GitHub state/current.json     (fallback — CDN 1-5 min stale)

GitHub Pages PWA ── sab sources parallel me fetch + passphrase se decrypt ──► jo sabse naya ts de, wahi
                     └─► "Open Harness" → live link
```

## 1. Problem kya thi
- `cloudflared` quick tunnel har restart pe **naya hostname** deta hai.
- DSH ka launch token bhi **per-process random** hai (`processLaunchToken()` → `randomBytes`), yaani `?token=` bhi badalta hai.
- Notebooks A/B ~9.5h pe handoff karte hain → link + token badalte hain → Telegram pe naya link aata hai → manually kholna padta hai.

## 2. Kyun Supabase (aur GitHub akela kyun kaafi nahi)
Measured (is session me, asli GitHub repo pe):

| Source | Naya link dikhne me lag | Wajah |
|---|---|---|
| `raw.githubusercontent.com` | **0.1s / 73s / 148s / 177s** (erratic) | CDN `?cb=` cache-buster ignore karta hai |
| `api.github.com` (anonymous) | >150s | 60 req/hr/IP rate limit |
| `api.github.com` (**auth**) | **0.3s** | token app me nahi rakh sakte |
| **Supabase REST** | **~0.2s** | PostgREST dynamic hai, koi CDN cache nahi |

Isliye primary source = Supabase, aur GitHub sirf fallback.

## 3. Setup

Repo + Pages already deploy ho chuke hain: **https://claude-kaku6183213.github.io/dsh-link/**

### Step 1 — Supabase me table (ek baar)
Notebook khud bana leta hai (SCHEMA me add hai), par turant chahiye to Supabase SQL Editor me ye chala do:

```sql
create table if not exists launch_state(
  id int primary key, enc text, updated_at timestamptz not null default now());
alter table launch_state enable row level security;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'grant select on launch_state to anon';
    if not exists (select 1 from pg_policies
                   where schemaname = 'public' and tablename = 'launch_state' and policyname = 'dsh_link_public_read') then
      execute 'create policy dsh_link_public_read on launch_state for select to anon using (true)';
    end if;
  end if;
end $$;
notify pgrst, 'reload schema';
```

Ye table sirf **encrypted blob** rakhta hai (aur kuch nahi) — tumhare existing tables/data ko haath nahi lagta. `anon` role sirf ciphertext dekh sakta hai, plaintext link nahi (passphrase tumhare paas hai).

### Step 2 — `config.js`
`config.example.js` ko `config.js` bana ke Supabase **Project URL** + **anon public key** daalo
(Project Settings → API). Dono values public-safe hain — anon key client-side ke liye hi banti hai.

### Step 3 — Kaggle Secrets
| Secret | Value | Zaruri? |
|---|---|---|
| `LINK_PASSPHRASE` | app me daalne wala passphrase | **haan** |
| `LINK_DB` | `1` (default) — Supabase target on/off | optional |
| `LINK_TABLE` | `launch_state` (default) | optional |
| `LINK_API_URL` + `LINK_API_SECRET` | Cloudflare Worker endpoint | optional |
| `LINK_REPO` + `LINK_PAT` | GitHub fallback (fine-grained: Contents Read+write) | optional |

`LINK_BRANCH` / `LINK_PATH` / `LINK_SALT` bhi optional (defaults: `main` / `state/current.json` / `dsh-link-v1`).

### Step 4 — Notebooks patch karo
```bash
python3 notebook/patch_notebooks.py dsh-runner-a.ipynb dsh-runner-b.ipynb -o patched
```
- `patched/*.patched.ipynb` → Kaggle pe paste + **Save & Run All** (A me `NODE_NAME="A"`, B me `"B"`).
- `patched/*.diff.txt` → kya badla (source me +192 lines, koi line delete nahi hoti).

Patch karta hai:
1. `publish(status)` → `publish_remote(status)`
2. `renewer()` heartbeat → `link_heartbeat()` (har ~8 min refresh, isliye app stale nahi dikhata)
3. `shutdown()` → `publish_remote("offline", force=True)` (peer ne lease le li ho to skip)
4. `SCHEMA` me `launch_state` table + anon read policy
5. `INJECT_KEYS` me `LINK_*` (peer notebook ko bhi secrets mil jayein)

### Step 4b — Kaggle me deploy karne ke 2 tarike
1. **Bootstrap cell (recommended)** — `notebook/dsh-runner-a-bootstrap.ipynb` / `dsh-runner-b-bootstrap.ipynb`
   import karo (ya `notebook/bootstrap-cell-a.txt` / `-b.txt` ka content ek hi cell me paste karo).
   Ye har start pe **latest code GitHub se** uthata hai → aage kabhi Kaggle edit karne ki zarurat nahi.
2. **Poora patched notebook** — `notebook/patched/*.patched.ipynb` import/paste karo.

Zaroori baatein (inhi se handoff chalta hai):
- Kaggle notebook ka **slug exactly** `dsh-runner-a` / `dsh-runner-b` hona chahiye. Notebook **rename** karne se slug badal jata hai → peer push fail hoga.
- **API se push kiye gaye version ko Kaggle Secrets nahi milte** (secrets UI-level hote hain). Isliye deploy **UI se** karo (*Save & Run All*), ya peer-push karao (wo secrets inject karta hai).
- Har notebook me `LINK_PASSPHRASE` secret **attach** hona chahiye (Add-ons → Secrets).

### Step 5 — Phone pe install
Pages URL kholo → passphrase → **"Link aate hi khud open kar do"** on → browser menu → **Add to Home Screen**.

## 4. Files
| File | Kaam |
|---|---|
| `index.html`, `style.css`, `app.js` | Launcher PWA (passphrase gate, multi-source fetch, freshest-ts jeete, auto-open, 20s poll) |
| `sw.js`, `manifest.webmanifest`, `icon-*` | PWA install support |
| `config.js` / `config.example.js` | Supabase URL + anon key (public values) |
| `notebook/dsh_link_cell.py` | Publisher: AES-GCM encrypt + Supabase/Worker/GitHub targets |
| `notebook/patch_notebooks.py` | A/B notebooks me inject karne wala script |
| `notebook/patched/*` | Ready patched notebooks + diffs |
| `tools/setup_github.py` | Repo create + files push + Pages enable + verify (idempotent) |
| `tools/push_kaggle.py` | Patched notebook ko Kaggle pe push (`--dry-run` / `--wait`) — metadata preserve karta hai, RUNNING hone pe rok deta hai |
| `tools/deploy_worker.py` | Optional Cloudflare Worker + KV deploy (pure REST, wrangler nahi chahiye) |
| `state/current.json` | GitHub fallback ka encrypted state |

## 5. Verification (is session me chalaya gaya)
| Test | Result |
|---|---|
| Publisher: db + worker + github teeno targets, upsert SQL, offline payload, 8-min throttle, handoff guard | **16/16 ✅** |
| App multi-source: Supabase fresh jeete / GitHub fallback / table-missing fallback / Waiting | **4/4 ✅** (Playwright + Chromium) |
| Python AES-GCM → browser WebCrypto decrypt (round trip, galat passphrase reject) | ✅ |
| Live GitHub infra: publisher → repo → Pages app URL resolve | ✅ |
| CDN staleness measurement (raw vs api anon vs api auth) | ✅ (table upar) |
| Patched notebooks compile clean, A/B big-cell identical | ✅ |

## 6. Troubleshooting
| Symptom | Fix |
|---|---|
| App "Waiting" | Notebook logs me `launcher: koi target configured nahi` ya `launcher[db] error` dekho; Kaggle secrets + table check karo |
| Supabase 404 / `42P01` | Step 1 ka SQL chalao (ya notebook ek baar restart karo), phir `notify pgrst, 'reload schema';` |
| 401 `no apikey` | `config.js` me anon key galat/khaali |
| "Passphrase galat lag rahi hai" | Notebook ka `LINK_PASSPHRASE` == app ka passphrase; `LINK_SALT` bhi same ho |
| Link 1-3 min purana | GitHub raw path use ho raha hai — Supabase config check karo |
| "Stale (>25 min)" | Harness crash/restart me hai; next publish pe theek ho jayega |

## 7. Optional upgrades
1. **Fixed URL proxy (Cloudflare Worker + KV)** — browser ko hamesha ek hi URL dikhe (WebSocket bhi proxy), cookie persist kare → phir PWA ki zarurat bhi nahi. `tools/deploy_worker.py` ready hai.
2. **Permanent hostname** — Cloudflare Named Tunnel + domain ya Tailscale Funnel (`*.ts.net`, free). DSH ka cookie-signing secret `dsh_home` me persist hota hai (jo DB me backup hota hai) aur cookie host-based hai → ek baar login ke baad bookmark hamesha chalega.
3. **Android APK** — chaaho to yahi launcher Capacitor se APK me package ho sakta hai (main bana dunga).
