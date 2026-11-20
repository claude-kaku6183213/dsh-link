#!/usr/bin/env python3
"""Patched notebook ko Kaggle pe push karta hai — metadata pull karke settings preserve karta hai.

Safety: agar notebook RUNNING/QUEUED hai to push nahi karta (--force se override).
Push ka matlab: naya version + turant run. Isliye soch samajh ke chalao.

Usage:
    python3 tools/push_kaggle.py a --dry-run        # kya push hoga, dekho (kuch nahi bhejta)
    python3 tools/push_kaggle.py a                  # push karo
    python3 tools/push_kaggle.py a --wait           # push + status + log me launcher lines
    python3 tools/push_kaggle.py b --force          # RUNNING hone pe bhi (aakhri raasta)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATCHED = ROOT / "notebook" / "patched"
SLUG = {"a": "dsh-runner-a", "b": "dsh-runner-b"}
DEFAULT_USER = "vishalmittal441"
BUSY = ("RUNNING", "QUEUED")


def kg(args, timeout=300):
    r = subprocess.run(["kaggle"] + args, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).strip()


def status(user, slug):
    _, out = kg(["kernels", "status", f"{user}/{slug}"])
    up = out.upper()
    for s in ("RUNNING", "QUEUED", "COMPLETE", "ERROR", "CANCEL"):
        if s in up:
            return s
    return out[-80:]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("which", choices=["a", "b"])
    ap.add_argument("--user", default=DEFAULT_USER)
    ap.add_argument("--notebook", help="patched ipynb ka path (default auto)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="RUNNING hone pe bhi push")
    ap.add_argument("--wait", action="store_true", help="push ke baad status + log dekhо")
    args = ap.parse_args()

    slug = SLUG[args.which]
    ref = f"{args.user}/{slug}"
    nb = Path(args.notebook) if args.notebook else PATCHED / f"{slug}.patched.ipynb"
    if not nb.exists():
        print(f"[FAIL] patched notebook nahi mila: {nb}", file=sys.stderr)
        return 2
    local = nb.read_bytes()

    st = status(args.user, slug)
    print(f"[1/4] {ref} status = {st}")
    if st in BUSY and not args.force and not args.dry_run:
        print(f"[STOP] notebook {st} hai. Push karne se ye version replace/queue ho sakta hai.\n"
              f"       Pehle doosra node handover kare (ya --force use karo, ya editor se Save & Run All).", file=sys.stderr)
        return 3

    tmp = Path(tempfile.mkdtemp(prefix="dshpush-"))
    rc, out = kg(["kernels", "pull", ref, "-p", str(tmp), "-m"])
    if rc != 0:
        print("[FAIL] metadata pull:", out[-300:], file=sys.stderr)
        return 4
    meta_path = tmp / "kernel-metadata.json"
    meta = json.loads(meta_path.read_text())
    code_file = meta.get("code_file") or f"{slug}.ipynb"
    print(f"[2/4] metadata mila: id={meta.get('id')} private={meta.get('is_private')} "
          f"internet={meta.get('enable_internet')} gpu={meta.get('enable_gpu')} code_file={code_file}")

    (tmp / code_file).write_bytes(local)
    meta["id"] = ref
    meta["code_file"] = code_file
    meta_path.write_text(json.dumps(meta, indent=2))

    # sanity: patched file me kya hona chahiye
    src = json.loads(local)["cells"]
    allsrc = "".join("".join(c.get("source", [])) if isinstance(c.get("source"), list) else c.get("source", "") for c in src)
    checks = {
        "publish_remote hook": "publish_remote(status)" in allsrc,
        "link_heartbeat": "link_heartbeat()" in allsrc,
        "launch_state DDL": "create table if not exists launch_state(" in allsrc,
        "LINK_* inject keys": '"LINK_PASSPHRASE"' in allsrc,
    }
    print("[3/4] patched file checks: " + "  ".join(f"{k}={'✅' if v else '❌'}" for k, v in checks.items())
          + f"  (size {len(local)} bytes)")
    if not all(checks.values()):
        print("[FAIL] patched file adhoora hai", file=sys.stderr)
        return 5

    if args.dry_run:
        print(f"[dry-run] yahan push hota: {ref} (version +1, run turant start). Kuch bheja nahi gaya.")
        print(f"[dry-run] dir: {tmp}")
        return 0

    rc, out = kg(["kernels", "push", "-p", str(tmp)])
    print(f"[4/4] push: rc={rc} {out[-200:]}")
    if rc != 0:
        return 6

    if args.wait:
        for i in range(30):
            time.sleep(20)
            s = status(args.user, slug)
            print(f"      +{i * 20:>3}s status = {s}")
            if s in ("COMPLETE", "ERROR", "CANCEL"):
                break
        outp = tmp / "out"
        kg(["kernels", "output", ref, "-p", str(outp)], timeout=600)
        if Path(outp).exists():
            for p in Path(outp).rglob("*.log"):
                lines = [l for l in p.read_text(errors="replace").splitlines() if "launcher" in l or "lease" in l or "stack up" in l]
                print(f"      --- {p.name} (relevant lines) ---")
                print("\n".join(lines[-25:]) or "      (koi launcher/lease line nahi)")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
