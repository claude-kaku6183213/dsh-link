# ============================================================ DSH LINK PUBLISHER
# Ye block notebook ke publish()/shutdown()/renewer() se call hota hai aur current
# tunnel link (AES-GCM encrypted) ko in targets me se jitne configured hain unme likhta hai:
#
#   1. SUPABASE table  (default ON, koi extra token nahi -- wahi DATABASE_URL connection)
#   2. HTTP endpoint   (optional, e.g. Cloudflare Worker) -- LINK_API_URL + LINK_API_SECRET
#   3. GitHub repo     (optional backup)                   -- LINK_REPO + LINK_PAT
#
# Required Kaggle Secrets: LINK_PASSPHRASE   (optional: LINK_DB=0 se supabase off)
# App inhi me se sabse fresh payload uthaati hai.

LINK_PASSPHRASE = secret("LINK_PASSPHRASE")
LINK_TABLE = secret("LINK_TABLE", "launch_state")
LINK_DB_ON = str(secret("LINK_DB", "1")).strip().lower() not in ("0", "false", "no", "off")
LINK_API_URL = secret("LINK_API_URL")
LINK_API_SECRET = secret("LINK_API_SECRET")
LINK_REPO = secret("LINK_REPO")
LINK_PAT = secret("LINK_PAT")
LINK_BRANCH = secret("LINK_BRANCH", "main")
LINK_PATH = secret("LINK_PATH", "state/current.json")
LINK_SALT = secret("LINK_SALT", "dsh-link-v1")
LINK_ITER = 200000
LINK_MIN_INTERVAL = 480                          # heartbeat re-publish interval (sec)
LINK_GH_INTERVAL = 3600                          # github fallback: itna hi baar commit (repo bloat se bacho)
LINK_API = os.environ.get("GITHUB_API_BASE", "https://api.github.com")

if not re.match(r"^[a-z_][a-z0-9_]*$", LINK_TABLE):     # config se aaya naam, validate kar lo
    raise SystemExit("LINK_TABLE invalid: " + LINK_TABLE)

LINK = {"status": None, "at": 0.0, "warned": False, "err_logged": 0.0, "gh_status": None, "gh_at": 0.0}


def _link_blob(payload):
    """AES-GCM encrypt karke encrypted-envelope JSON return karta hai (browser WebCrypto compatible)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=LINK_SALT.encode(), iterations=LINK_ITER)
    key = kdf.derive(LINK_PASSPHRASE.encode())
    iv = os.urandom(12)
    ct = AESGCM(key).encrypt(iv, json.dumps(payload).encode(), None)
    b64 = lambda x: base64.b64encode(x).decode()
    return json.dumps({"v": 1, "alg": "AES-GCM", "kdf": "PBKDF2-SHA256",
                       "it": LINK_ITER, "salt": LINK_SALT, "iv": b64(iv), "ct": b64(ct)}, indent=1)


# ------------------------------------------------------------------ target 1: supabase/postgres
def _link_db_push(blob):
    db(f"insert into {LINK_TABLE}(id, enc, updated_at) values (1, %s, now()) "
       f"on conflict (id) do update set enc = excluded.enc, updated_at = now()", (blob,))
    return True


# ------------------------------------------------------------------ target 2: http (worker)
def _link_api_push(blob):
    req = urllib.request.Request(LINK_API_URL, data=blob.encode(), method="POST")
    req.add_header("Authorization", "Bearer " + LINK_API_SECRET)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "dsh-link/1.0")
    with urllib.request.urlopen(req, timeout=25) as r:
        return 200 <= r.status < 300


# ------------------------------------------------------------------ target 3: github
def _link_gh(method, url, body=None):
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", "Bearer " + LINK_PAT)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "dsh-link/1.0")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _link_gh_push(blob, msg):
    base = f"{LINK_API}/repos/{LINK_REPO}/contents/{LINK_PATH}"
    content = base64.b64encode(blob.encode()).decode()
    for attempt in range(3):
        sha = None
        try:
            sha = _link_gh("GET", f"{base}?ref={urllib.parse.quote(LINK_BRANCH)}").get("sha")
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
        body = {"message": msg, "content": content, "branch": LINK_BRANCH}
        if sha:
            body["sha"] = sha
        try:
            _link_gh("PUT", base, json.dumps(body).encode())
            return True
        except urllib.error.HTTPError as e:
            if e.code in (409, 422, 500) and attempt < 2:
                time.sleep(2 + attempt * 3)
                continue
            raise
    return False


def _link_targets():
    t = []
    if LINK_DB_ON and DATABASE_URL:
        t.append("db")
    if LINK_API_URL and LINK_API_SECRET:
        t.append("api")
    if LINK_REPO and LINK_PAT:
        t.append("github")
    return t


def _link_still_mine():
    """Handoff ke baad purana node naye node ka 'online' status overwrite na kare."""
    try:
        return bool(db("select 1 from runtime_info where id = 1 and holder = %s", (NODE_NAME,), fetch=True, tries=2))
    except Exception:
        return True


def publish_remote(status, force=False):
    """Best-effort: link state configured targets me likho. Kabhi exception nahi throw karta."""
    try:
        targets = _link_targets()
        if not LINK_PASSPHRASE or not targets:
            if not LINK["warned"]:
                LINK["warned"] = True
                log("launcher: koi target configured nahi (LINK_PASSPHRASE + LINK_DB ya LINK_API_URL/SECRET ya LINK_REPO/PAT) -> app link publish off")
            return False
        if status != "offline" and not S.launch_url:
            return False
        if status == "offline" and not _link_still_mine():
            log("launcher: peer already took over, offline write skipped")
            return False
        now = time.time()
        if not force and LINK["status"] == status and now - LINK["at"] < LINK_MIN_INTERVAL:
            return False
        payload = {"v": 1, "status": status, "node": NODE_NAME, "ts": int(now)}
        if status != "offline":
            payload["url"] = S.launch_url
            payload["public"] = f"https://{S.host}/" if S.host else None
        blob = _link_blob(payload)
        msg = f"dsh-link: {status} [{NODE_NAME}] {time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime(now))}"
        gh_due = force or status != LINK["gh_status"] or (now - LINK["gh_at"]) > LINK_GH_INTERVAL
        done = []
        for t in targets:
            try:
                if t == "db":
                    _link_db_push(blob)
                elif t == "api":
                    _link_api_push(blob)
                else:
                    if not gh_due:
                        continue
                    _link_gh_push(blob, msg)
                    LINK["gh_status"], LINK["gh_at"] = status, now
                done.append(t)
            except Exception as e:
                log(f"launcher[{t}] error: {type(e).__name__}: {str(e)[:160]}")
        if done:
            LINK["status"], LINK["at"] = status, now
            log(f"launcher: published '{status}' -> {','.join(done)}")
            return True
        return False
    except Exception as e:
        if time.time() - LINK["err_logged"] > 300:
            LINK["err_logged"] = time.time()
            log(f"launcher publish error: {type(e).__name__}: {str(e)[:200]}")
        return False


def link_heartbeat():
    """renewer() se har 30s call hota hai; actual write LINK_MIN_INTERVAL pe throttle hoti hai."""
    if LINK.get("status") in ("online", "handoff", "starting"):
        publish_remote(LINK["status"])
