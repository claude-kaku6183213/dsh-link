# ============================================================ DSH LINK PUBLISHER
# Ye block notebook ke andar publish()/shutdown()/renewer() se call hota hai aur
# GitHub repo ke state/current.json me current tunnel link (encrypted) likh deta hai.
# Required Kaggle Secrets: LINK_REPO, LINK_PAT, LINK_PASSPHRASE
# Optional: LINK_BRANCH (default main), LINK_PATH (default state/current.json),
#           LINK_SALT (default dsh-link-v1 -- app.js ke salt se match karna chahiye)

LINK_REPO = secret("LINK_REPO")                  # "username/repo"
LINK_PAT = secret("LINK_PAT")                    # fine-grained PAT: Contents = Read and write
LINK_PASSPHRASE = secret("LINK_PASSPHRASE")      # app me yahi passphrase daalna hai
LINK_BRANCH = secret("LINK_BRANCH", "main")
LINK_PATH = secret("LINK_PATH", "state/current.json")
LINK_SALT = secret("LINK_SALT", "dsh-link-v1")
LINK_ITER = 200000
LINK_MIN_INTERVAL = 480                          # heartbeat re-publish interval (sec)
LINK_API = os.environ.get("GITHUB_API_BASE", "https://api.github.com")

LINK = {"status": None, "at": 0.0, "warned": False, "err_logged": 0.0}


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


def _link_push(text, msg):
    base = f"{LINK_API}/repos/{LINK_REPO}/contents/{LINK_PATH}"
    content = base64.b64encode(text.encode()).decode()
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


def _link_still_mine():
    """Handoff ke baad purana node naye node ka 'online' status overwrite na kare."""
    try:
        return bool(db("select 1 from runtime_info where id = 1 and holder = %s", (NODE_NAME,), fetch=True, tries=2))
    except Exception:
        return True


def publish_remote(status, force=False):
    """Best-effort: link state GitHub pe likho. Kabhi exception nahi throw karta."""
    try:
        if not (LINK_REPO and LINK_PAT and LINK_PASSPHRASE):
            if not LINK["warned"]:
                LINK["warned"] = True
                log("launcher: LINK_REPO/LINK_PAT/LINK_PASSPHRASE secrets missing -> app link publish off")
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
        _link_push(_link_blob(payload), f"dsh-link: {status} [{NODE_NAME}] {time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime(now))}")
        LINK["status"], LINK["at"] = status, now
        log(f"launcher: published '{status}' to {LINK_REPO}/{LINK_PATH}")
        return True
    except Exception as e:
        if time.time() - LINK["err_logged"] > 300:
            LINK["err_logged"] = time.time()
            log(f"launcher publish error: {type(e).__name__}: {str(e)[:200]}")
        return False


def link_heartbeat():
    """renewer() se har 30s call hota hai; actual write LINK_MIN_INTERVAL pe throttle hoti hai."""
    if LINK.get("status") in ("online", "handoff", "starting"):
        publish_remote(LINK["status"])
