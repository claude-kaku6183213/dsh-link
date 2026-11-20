# DSH Link — Kaggle DSH harness ka apna launcher app

Ek chhota **GitHub Pages PWA** jo tumhare Kaggle DSH harness ka **latest tunnel link khud dhundh leta hai**.
Har restart/handoff ke baad naya `https://xxxx.trycloudflare.com/?token=…` link kholne ki zarurat nahi —
phone/PC pe app icon kholo → **Open Harness** (ya auto-open on rakho). Link backend me apne aap update hota rehta hai.

---

## 1. Problem kya thi

- `cloudflared` quick tunnel har restart pe **naya random hostname** deta hai.
- DSH ka launch token bhi **per-process random** hai (`processLaunchToken()` → `randomBytes`), yaani URL ka `?token=` bhi har restart pe badalta hai.
- Tumhare notebooks A/B har ~9.5h pe handoff karte hain → link + token dono badalte hain → Telegram pe naya link aata hai → wahi manually kholna padta hai.

## 2. Ye solution kaise kaam karta hai

```
Kaggle notebook A / B
  publish("online"|"handoff")  ─┐
  renewer()   → link_heartbeat() ├─►  AES-GCM (PBKDF2-SHA256) encrypted JSON
  shutdown()  → "offline"      ─┘         │
                                          ▼
                        GitHub repo:  state/current.json      (public repo, par content encrypted)
                                          ▲
                                          │ raw.githubusercontent (cache-buster ke saath, har 20s)
                        GitHub Pages PWA ─┘
                             │ passphrase se browser me decrypt
                             ▼
                  "Open Harness"  →  https://xxx.trycloudflare.com/?token=…
```

- **Repo public ho sakta hai** — state file encrypted hai (AES-GCM 256, PBKDF2 200k iterations). Passphrase sirf tumhare paas: Kaggle secret + app me ek baar type.
- App har **20 second** me state file dobara padhti hai, isliye handoff ke thodi der baad khud latest link aa jata hai.
- Link ki value short-lived hoti hai (tunnel restart pe woh URL mar jata hai), aur passphrase badalte hi purana ciphertext useless ho jata hai.

## 3. Setup (5 steps, ~10 min)

> **Automated:** `GH_TOKEN=<token> python3 tools/setup_github.py` — ek hi command me repo create, 20 files push,
> Pages enable, build wait + live URL/state file ka HTTP verify. (Token env me do, argv me nahi.)
> Manual steps neeche diye hain — audit ya alternate ke liye.

### Step 1 — Repo
1. GitHub pe naya **public** repo banao, e.g. `dsh-link`.
2. Is folder ki saari files us repo me push kar do (`state/current.json` placeholder ke saath).

### Step 2 — GitHub Pages on karo
Settings → **Pages** → Source: `Deploy from a branch` → Branch: **main** / **/ (root)** → Save.
URL milega: `https://<username>.github.io/dsh-link/`

### Step 3 — Kaggle Secrets add karo
Kaggle notebook → Add-ons → Secrets. (Dono notebooks ke liye same Kaggle account, to secrets automatically available hain.)

| Secret | Value | Zaruri? |
|---|---|---|
| `LINK_REPO` | `username/dsh-link` | **haan** |
| `LINK_PAT` | fine-grained PAT — sirf usi repo pe permission **Contents: Read and write** | **haan** |
| `LINK_PASSPHRASE` | koi bhi strong passphrase (yahi app me daalni hai) | **haan** |
| `LINK_BRANCH` | `main` (default `main`) | optional |
| `LINK_PATH` | `state/current.json` (default wahi) | optional |
| `LINK_SALT` | `dsh-link-v1` (default wahi, app.js ke saath match hona chahiye) | optional |

> PAT expire hone pe link update ruk jayega — expiry "No expiration" ya lambi rakho.

### Step 4 — Notebooks patch karo
```bash
python3 notebook/patch_notebooks.py dsh-runner-a.ipynb dsh-runner-b.ipynb -o patched
```
Ye banata hai:
- `patched/dsh-runner-a.patched.ipynb`, `patched/dsh-runner-b.patched.ipynb` → Kaggle pe paste karke **Save & Run All** (A me `NODE_NAME="A"`, B me `"B"` — pehle jaisa hi).
- `patched/*.diff.txt` → exactly kya badla, review ke liye (+120 lines, koi existing line delete nahi hoti).

Patch kya karta hai (4 chhote hooks):
1. `publish(status)` → `publish_remote(status)` — naya link publish.
2. `renewer()` heartbeat → `link_heartbeat()` — har ~8 min me timestamp refresh (isliye app "stale" nahi dikhata).
3. `shutdown()` → `publish_remote("offline", force=True)` — band hone pe offline mark.
4. `INJECT_KEYS` me `LINK_*` add — taaki peer notebook (B) ko bhi secrets mil jayein.

Manual chaho to: `notebook/dsh_link_cell.py` ka poora block `def main():` se pehle paste karo, aur upar wale 4 hooks haath se laga do.

### Step 5 — Phone/PC pe install
Pages URL kholo → passphrase daalo → **"Link aate hi khud open kar do"** on karo → browser menu → **Add to Home Screen**.
Bas: icon kholo, link khud aata hai, tap karo (ya auto-open).

---

## 4. Files

| File | Kaam |
|---|---|
| `index.html`, `style.css`, `app.js` | Launcher PWA (passphrase gate + status + Open/Copy + auto-open + 20s poll) |
| `sw.js`, `manifest.webmanifest`, `icon-*` | PWA install support + icons |
| `notebook/dsh_link_cell.py` | Notebook me jaane wala publisher block (AES-GCM encrypt + GitHub Contents API write) |
| `notebook/patch_notebooks.py` | A/B notebooks me automatically inject karne wala script |
| `notebook/patched/*` | Ready patched notebooks + diffs |
| `state/current.json` | Live link ka encrypted state (notebook likhta hai, app padhti hai) |
| `config.example.js` | Sirf local test / custom domain / custom backend ke liye (`config.js` gitignored hai) |

## 5. Is session me kya verify kiya gaya

| Test | Result |
|---|---|
| Python `AESGCM`+`PBKDF2` envelope → browser **WebCrypto** decrypt (round trip) | ✅ |
| Galat passphrase reject (browser) | ✅ `OperationError` |
| `publish_remote()` vs **mock GitHub API**: write, 409-conflict retry, 8-min throttle, force, offline | ✅ |
| Handoff guard: peer ne lease le liya → purana node naya link overwrite nahi karta | ✅ |
| Playwright + chromium: online / wrong-pass / offline / stale / placeholder / file-missing | ✅ (6/6 states) |
| Patched notebooks `compile()` clean, A aur B ka big cell bilkul identical | ✅ |
| Full loop: Python publisher → GitHub file → browser launcher me URL resolve | ✅ |

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| App "Waiting" pe atki hai | Notebook logs me `launcher: LINK_REPO/LINK_PAT/LINK_PASSPHRASE secrets missing` dekho → Step 3 ke secrets add karo, notebook restart karo |
| "Passphrase galat lag rahi hai" | Notebook ka `LINK_PASSPHRASE` == app ka passphrase. `LINK_SALT` bhi dono taraf same ho |
| GitHub 401/403 (notebook log me) | PAT ka permission `Contents: Read and write` (usi repo pe) aur expiry check karo |
| 404 on state file | `LINK_BRANCH`/`LINK_PATH` galat hain, ya notebook ne abhi publish nahi kiya |
| "Stale (>25 min)" | Harness crash/restart me hai; next publish pe app khud theek ho jayega |
| Pages pe purani file dikhe | App cache-buster lagati hai; phir bhi aaye to hard refresh (Ctrl+Shift+R) |

## 7. Optional upgrades (bolo to bana du)

1. **Permanent URL proxy (Cloudflare Worker + KV)** — notebook KV me current origin+token likhe aur Worker poora traffic (WebSocket included) proxy kare. Browser ko hamesha `https://dsh-link.<sub>.workers.dev/` hi dikhta hai, cookie bhi persist karta hai — is case me PWA ki zarurat bhi nahi, ek bookmark kaafi.
2. **Root fix: fixed hostname** — Cloudflare **Named Tunnel** + sasta domain (`dsh.tumharadomain.com`) ya **Tailscale Funnel** (`node.tailnet.ts.net`, free, fixed hostname). DSH ka cookie-signing secret `dsh_home` me persist hota hai (jo tum already DB me backup karte ho) aur cookie host-based hoti hai — matlab ek baar login ke baad `https://fixed-host/` **hamesha** chalega, token ki bhi zarurat nahi. Ye sabse saaf solution hai; launcher app optional ho jaati hai.
3. **Telegram bot `/link`** — tumhare paas TG bot already hai; usi me current link command add ho sakta hai.
