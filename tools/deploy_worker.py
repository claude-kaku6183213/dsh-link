#!/usr/bin/env python3
"""Cloudflare Worker + KV deploy (koi npm/wrangler nahi chahiye — sirf REST API).

Ye script:
  1. CF API token verify + account id nikalta hai
  2. KV namespace `dsh-link` banata hai (ya pehle se ho to reuse)
  3. cloudflare/worker.js ko module worker ke roop me deploy karta hai
  4. PUBLISH_SECRET secret set karta hai
  5. workers.dev subdomain enable karke final URL deta hai

Usage:
    CF_API_TOKEN=xxx PUBLISH_SECRET=yyy python3 tools/deploy_worker.py
    CF_API_TOKEN_FILE=~/.cf_token PUBLISH_SECRET_FILE=~/.dsh_publish_secret python3 tools/deploy_worker.py

Token permissions (Cloudflare → My Profile → API Tokens → Custom token):
    Account → Workers Scripts      → Edit
    Account → Workers KV Storage   → Edit
    User    → User Details         → Read
    Account → Account Settings     → Read   (account id ke liye)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

API = "https://api.cloudflare.com/client/v4"
HERE = Path(__file__).resolve().parent
WORKER = HERE.parent / "cloudflare" / "worker.js"
SCRIPT = "dsh-link"
KV_TITLE = "dsh-link"


def cf(method: str, path: str, token: str, body=None, content_type="application/json", raw=False):
    data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
    r = urllib.request.Request(API + path, data=data, method=method)
    r.add_header("Authorization", "Bearer " + token)
    r.add_header("Content-Type", content_type)
    r.add_header("User-Agent", "dsh-link-deploy/1.0")
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            payload = resp.read()
            return resp.status, (payload if raw else json.loads(payload))
    except urllib.error.HTTPError as e:
        payload = e.read()
        try:
            return e.code, json.loads(payload)
        except Exception:
            return e.code, {"raw": payload[:400].decode("utf-8", "replace")}


def first_account(token):
    st, out = cf("GET", "/accounts?per_page=50", token)
    if st != 200 or not out.get("success"):
        raise SystemExit(f"[FAIL] accounts list: HTTP {st} {json.dumps(out)[:300]}")
    accts = out["result"]
    if not accts:
        raise SystemExit("[FAIL] koi Cloudflare account nahi mila is token ke saath")
    if len(accts) > 1:
        print(f"[i] {len(accts)} accounts mile, pehla use kar raha hoon: {accts[0]['name']}")
    return accts[0]["id"], accts[0]["name"]


def ensure_kv(token, account_id):
    st, out = cf("GET", f"/accounts/{account_id}/storage/kv/namespaces?per_page=100", token)
    if st == 200 and out.get("success"):
        for ns in out["result"]:
            if ns.get("title") == KV_TITLE:
                print(f"[2/5] KV namespace already hai: {ns['id']}")
                return ns["id"]
    st, out = cf("POST", f"/accounts/{account_id}/storage/kv/namespaces", token, {"title": KV_TITLE})
    if st not in (200, 201) or not out.get("success"):
        raise SystemExit(f"[FAIL] KV create: HTTP {st} {json.dumps(out)[:300]}")
    print(f"[2/5] KV namespace bana: {out['result']['id']}")
    return out["result"]["id"]


def multipart(metadata: dict, filename: str, source: bytes, content_type: str):
    b = "----dsh" + uuid.uuid4().hex
    parts = []
    parts.append(f"--{b}\r\nContent-Disposition: form-data; name=\"metadata\"; filename=\"metadata.json\"\r\n"
                 f"Content-Type: application/json\r\n\r\n".encode() + json.dumps(metadata).encode() + b"\r\n")
    parts.append(f"--{b}\r\nContent-Disposition: form-data; name=\"{filename}\"; filename=\"{filename}\"\r\n"
                 f"Content-Type: {content_type}\r\n\r\n".encode() + source + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={b}"


def deploy_script(token, account_id, kv_id):
    metadata = {
        "main_module": "worker.js",
        "compatibility_date": "2025-01-01",
        "bindings": [{"type": "kv_namespace", "name": "DSH_LINK", "namespace_id": kv_id}],
    }
    src = WORKER.read_bytes()
    body, ctype = multipart(metadata, "worker.js", src, "application/javascript+module")
    st, out = cf("PUT", f"/accounts/{account_id}/workers/scripts/{SCRIPT}", token, body, ctype)
    if st not in (200, 201) or not out.get("success"):
        raise SystemExit(f"[FAIL] worker deploy: HTTP {st} {json.dumps(out)[:400]}")
    print(f"[3/5] worker deploy ho gaya ({len(src)} bytes)")


def put_secret(token, account_id, secret):
    st, out = cf("PUT", f"/accounts/{account_id}/workers/scripts/{SCRIPT}/secrets", token,
                 {"name": "PUBLISH_SECRET", "text": secret, "type": "secret_text"})
    if st not in (200, 201) or not out.get("success"):
        raise SystemExit(f"[FAIL] secret set: HTTP {st} {json.dumps(out)[:300]}")
    print("[4/5] PUBLISH_SECRET set ho gaya")


def ensure_subdomain(token, account_id, want):
    st, out = cf("GET", f"/accounts/{account_id}/workers/subdomain", token)
    if st == 200 and out.get("success") and out["result"].get("subdomain"):
        return out["result"]["subdomain"]
    st, out = cf("PUT", f"/accounts/{account_id}/workers/subdomain", token, {"subdomain": want})
    if st != 200 or not out.get("success"):
        raise SystemExit(f"[FAIL] workers.dev subdomain: HTTP {st} {json.dumps(out)[:300]}")
    return out["result"]["subdomain"]


def main() -> int:
    token = os.environ.get("CF_API_TOKEN", "").strip()
    if not token and os.environ.get("CF_API_TOKEN_FILE"):
        token = Path(os.environ["CF_API_TOKEN_FILE"]).expanduser().read_text().strip()
    secret = os.environ.get("PUBLISH_SECRET", "").strip()
    if not secret and os.environ.get("PUBLISH_SECRET_FILE"):
        secret = Path(os.environ["PUBLISH_SECRET_FILE"]).expanduser().read_text().strip()
    if not token:
        print("[FAIL] CF_API_TOKEN (ya CF_API_TOKEN_FILE) do", file=sys.stderr)
        return 2
    if not secret:
        print("[FAIL] PUBLISH_SECRET (ya PUBLISH_SECRET_FILE) do", file=sys.stderr)
        return 2

    st, out = cf("GET", "/user/tokens/verify", token)
    print(f"[1/5] token verify: HTTP {st} {json.dumps(out.get('result', out))[:120]}")
    if st != 200 or not out.get("success"):
        print("[FAIL] token invalid / permissions adhoori", file=sys.stderr)
        return 2

    account_id, account_name = first_account(token)
    print(f"      account: {account_name} ({account_id})")
    kv_id = ensure_kv(token, account_id)
    deploy_script(token, account_id, kv_id)
    put_secret(token, account_id, secret)
    sub = ensure_subdomain(token, account_id, "dsh-link-" + account_id[:8].lower())
    base = f"https://{SCRIPT}.{sub}.workers.dev"
    print(f"[5/5] done")
    print()
    print("=" * 68)
    print(f"  Publish URL : {base}/publish")
    print(f"  State URL   : {base}/state")
    print(f"  Health      : {base}/healthz   → {base}/healthz")
    print("=" * 68)
    print(f"""
Kaggle secrets (GitHub wale LINK_REPO/LINK_PAT ki ab zarurat nahi):
   LINK_PASSPHRASE  = <app ka passphrase>
   LINK_API_URL     = {base}/publish
   LINK_API_SECRET  = <wahi PUBLISH_SECRET>

app-config (repo me config.js):
   stateUrl: '{base}/state'
""")
    verify(base)
    return 0


def verify(base):
    try:
        with urllib.request.urlopen(base + "/healthz", timeout=20) as r:
            print("healthz:", r.status, r.read().decode()[:80])
        with urllib.request.urlopen(base + "/state", timeout=20) as r:
            print("state  :", r.status, r.headers.get("cache-control"), r.read().decode()[:60])
    except Exception as e:
        print("[!] verify fail:", type(e).__name__, e)
        print("    (workers.dev propagate hone me 10-20s lag sakte hain — dobara /healthz check karo)")


if __name__ == "__main__":
    sys.exit(main())
