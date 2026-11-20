#!/usr/bin/env python3
"""DSH Link ka poora GitHub setup ek command me.

Karta hai:
  1. token verify (GET /user)
  2. repo create (default: public, auto-init)
  3. repo ki saari files push (Contents API, idempotent -- dobara chalane pe update ho jaata hai)
  4. GitHub Pages enable (branch main, path /)
  5. Pages build ka wait + live URL + state file ka HTTP check

Usage:
    GH_TOKEN=ghp_xxx python3 tools/setup_github.py
    python3 tools/setup_github.py --token-file ~/.gh_token --repo-name dsh-link
    python3 tools/setup_github.py --dry-run          # token ke bina: files + plan dekho

Token ko argv me mat do (process list me dikhta hai) -- env ya --token-file use karo.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.github.com"
ROOT = Path(__file__).resolve().parent.parent
BRANCH = "main"

SKIP_DIRS = {".git", "__pycache__", ".github"}
SKIP_FILES = {"config.local.js"}          # config.js public-safe hai, isliye push hoti hai
SKIP_SUFFIX = {".zip", ".pyc"}


def req(method: str, path: str, token: str, body=None, allow=(200, 201, 204, 404, 409, 422, 403)):
    """Ek API call. (status, parsed_json) return karta hai; HTTPError bhi status ke saath."""
    url = path if path.startswith("http") else API + path
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Authorization", "Bearer " + token)
    r.add_header("Accept", "application/vnd.github+json")
    r.add_header("X-GitHub-Api-Version", "2022-11-28")
    r.add_header("User-Agent", "dsh-link-setup/1.0")
    if data is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, timeout=45) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:300].decode("utf-8", "replace")}


def http_code(url: str, timeout=20):
    try:
        r = urllib.request.Request(url, headers={"User-Agent": "dsh-link-setup/1.0", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def repo_files():
    out = []
    for dp, dn, fn in os.walk(ROOT):
        dn[:] = sorted(d for d in dn if d not in SKIP_DIRS)
        for f in sorted(fn):                       # hidden files (.gitignore/.nojekyll) include hote hain
            if f in SKIP_FILES or Path(f).suffix in SKIP_SUFFIX or f.startswith(".") and f not in {".gitignore", ".nojekyll"}:
                continue
            p = Path(dp) / f
            out.append((str(p.relative_to(ROOT)), p.read_bytes()))
    return out


def push_tree(repo: str, token: str, files, quiet=False):
    changed = []
    for rel, blob in files:
        p = f"/repos/{repo}/contents/{urllib.parse.quote(rel)}"
        st, cur = req("GET", f"{p}?ref={BRANCH}", token)
        sha = cur.get("sha") if st == 200 and isinstance(cur, dict) else None
        body = {"message": f"dsh-link: {rel}", "content": base64.b64encode(blob).decode(), "branch": BRANCH}
        if sha:
            body["sha"] = sha
        st, out = req("PUT", p, token, body)
        if st not in (200, 201):
            raise SystemExit(f"[FAIL] push {rel}: HTTP {st} {json.dumps(out)[:200]}")
        changed.append(rel)
        if not quiet:
            print(f"   ↑ {rel} ({len(blob)} bytes)")
    return changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--token-file", help="file jisme GH_TOKEN likha ho")
    ap.add_argument("--repo-name", default="dsh-link")
    ap.add_argument("--private", action="store_true", help="private repo (Pages ke liye GitHub Pro chahiye)")
    ap.add_argument("--dry-run", action="store_true", help="token ke bina sirf files + plan dikhao")
    args = ap.parse_args()

    files = repo_files()
    print(f"[i] {len(files)} files push hongi ({ROOT})")
    if args.dry_run:
        for rel, blob in files:
            print(f"    {rel:52s} {len(blob):>7} bytes")
        print("\n[i] dry-run: koi API call nahi hui. Token ke saath chalao:")
        print("    GH_TOKEN=... python3 tools/setup_github.py")
        return 0

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    if not token and args.token_file:
        token = Path(args.token_file).expanduser().read_text().strip()
    if not token:
        print("[FAIL] GH_TOKEN env ya --token-file do", file=sys.stderr)
        return 2

    # 1 ---------------------------------------------------------------- who am I
    st, me = req("GET", "/user", token)
    if st != 200:
        print(f"[FAIL] token invalid: HTTP {st} {json.dumps(me)[:200]}", file=sys.stderr)
        return 2
    login = me["login"]
    repo = f"{login}/{args.repo_name}"
    print(f"[1/5] token OK → {login}  (scopes: {st and me.get('plan', {}) and 'n/a'})")

    # 2 ---------------------------------------------------------------- repo
    st, info = req("GET", f"/repos/{repo}", token)
    if st == 200:
        print(f"[2/5] repo exists: {info['html_url']}")
    else:
        st, out = req("POST", "/user/repos", token, {
            "name": args.repo_name,
            "private": bool(args.private),
            "auto_init": True,
            "description": "DSH Link — Kaggle DSH harness ka auto-updating launcher app",
            "has_issues": False, "has_wiki": False, "has_projects": False,
        })
        if st not in (200, 201):
            print(f"[FAIL] repo create: HTTP {st} {json.dumps(out)[:300]}", file=sys.stderr)
            print("       Manually repo bana lo, phir ye script dobara chalao.", file=sys.stderr)
            return 3
        print(f"[2/5] repo created: {out['html_url']}")
        time.sleep(3)

    # 3 ---------------------------------------------------------------- push files
    print(f"[3/5] files push kar raha hoon {BRANCH} pe…")
    push_tree(repo, token, files)

    # 4 ---------------------------------------------------------------- pages
    print("[4/5] GitHub Pages enable…")
    st, out = req("POST", f"/repos/{repo}/pages", token, {"source": {"branch": BRANCH, "path": "/"}})
    if st in (200, 201):
        print("      Pages enabled (API se)")
    elif st == 409:
        print("      Pages pehle se enabled tha")
    elif st == 403:
        print(f"      [!] API se enable nahi hua (403): {json.dumps(out)[:160]}")
        print("          Manual: Settings → Pages → Deploy from a branch → main / (root) → Save")
    else:
        print(f"      [!] Pages POST HTTP {st}: {json.dumps(out)[:200]}")
        print("          Manual: Settings → Pages → Deploy from a branch → main / (root) → Save")

    # 5 ---------------------------------------------------------------- wait + verify
    print("[5/5] Pages build ka wait…")
    html_url = f"https://{login}.github.io/{args.repo_name}/"
    state_raw = f"https://raw.githubusercontent.com/{repo}/{BRANCH}/state/current.json"
    up = False
    for i in range(24):
        code = http_code(html_url)
        if code == 200:
            up = True
            break
        time.sleep(5)
    print()
    print("=" * 68)
    print(f"  App URL      : {html_url}   {'✅ live' if up else '⏳ build ho raha hai (1-2 min)'}")
    print(f"  Repo         : https://github.com/{repo}")
    print(f"  State file   : {state_raw}")
    print(f"  State HTTP   : {http_code(state_raw + '?cb=%d' % int(time.time()))}")
    print("=" * 68)
    print("""
Ab Kaggle me ye 3 secrets add karo (Add-ons → Secrets), dono notebooks ke liye:
   LINK_REPO        = %s
   LINK_PAT         = <fine-grained token: usi repo pe Contents: Read and write>
   LINK_PASSPHRASE  = <wahi passphrase jo app me daaloge>

(Optional: LINK_BRANCH, LINK_PATH, LINK_SALT -- default main / state/current.json / dsh-link-v1)

Phir patched notebook Kaggle pe paste karke Save & Run All:
   notebook/patched/dsh-runner-a.patched.ipynb  (NODE_NAME="A")
   notebook/patched/dsh-runner-b.patched.ipynb  (NODE_NAME="B")
""" % repo)
    return 0 if up else 4


if __name__ == "__main__":
    sys.exit(main())
