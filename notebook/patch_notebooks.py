#!/usr/bin/env python3
"""dsh-runner-a.ipynb / dsh-runner-b.ipynb me DSH Link publisher inject karta hai.

Usage:
    python3 patch_notebooks.py dsh-runner-a.ipynb dsh-runner-b.ipynb -o out/

Har notebook ke liye banata hai:
    out/<name>.patched.ipynb   -- Kaggle pe upload karne wali file
    out/<name>.diff.txt        -- kya badla, review ke liye
"""
import argparse
import difflib
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HELPER = (HERE / "dsh_link_cell.py").read_text(encoding="utf-8").rstrip() + "\n"

ANCHOR_PUBLISH = '''def publish(status):
    db("update runtime_info set holder = %s, launch_url = %s, public_url = %s, status = %s, started_at = now(), heartbeat_at = now() where id = 1",
       (NODE_NAME, S.launch_url, f"https://{S.host}/", status))'''

ANCHOR_SHUTDOWN = """        db("update runtime_info set status = 'offline', launch_url = null, public_url = null where id = 1 and holder = %s", (NODE_NAME,))
        release_lease()"""

ANCHOR_RENEW = '''            db("update runtime_info set heartbeat_at = now() where id = 1 and holder = %s", (NODE_NAME,), tries=1)'''

NEW_KEYS = ('INJECT_KEYS = ["DATABASE_URL", "KAGGLE_USERNAME", "KAGGLE_KEY", "BACKUP_PASSPHRASE", "TG_TOKEN", "TG_CHAT_ID",\n'
            '               "DSH_VERSION", "HANDOFF_AFTER_H", "HARD_EXIT_H", "MAX_BACKUP_MB",\n'
            '               "LINK_PASSPHRASE", "LINK_DB", "LINK_TABLE", "LINK_API_URL", "LINK_API_SECRET",\n'
            '               "LINK_REPO", "LINK_PAT", "LINK_BRANCH", "LINK_PATH", "LINK_SALT"]')

# Supabase/Postgres: encrypted link state ke liye alag chhota table + anon read policy.
# Existing tables ko haath nahi lagta; anon sirf ciphertext dekh sakta hai.
SCHEMA_ANCHOR = 'alter table harness_backup enable row level security;\n"""'
SCHEMA_ADD = '''alter table harness_backup enable row level security;

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
"""'''


def cell_text(cell):
    src = cell.get("source", "")
    return "".join(src) if isinstance(src, list) else src


def set_cell_text(cell, text):
    cell["source"] = text.splitlines(keepends=True)


def patch_source(text):
    missing = []

    if ANCHOR_PUBLISH + "\n" not in text and ANCHOR_PUBLISH not in text:
        missing.append("publish()")
    else:
        text = text.replace(ANCHOR_PUBLISH, ANCHOR_PUBLISH + '\n    publish_remote(status)', 1)

    if ANCHOR_SHUTDOWN not in text:
        missing.append("shutdown() db update")
    else:
        text = text.replace(
            ANCHOR_SHUTDOWN,
            '''        db("update runtime_info set status = 'offline', launch_url = null, public_url = null where id = 1 and holder = %s", (NODE_NAME,))
        publish_remote("offline", force=True)
        release_lease()''', 1)

    if ANCHOR_RENEW not in text:
        missing.append("renewer() heartbeat")
    else:
        text = text.replace(ANCHOR_RENEW, ANCHOR_RENEW + '\n            link_heartbeat()', 1)

    if not re.search(r"INJECT_KEYS = \[", text):
        missing.append("INJECT_KEYS")
    else:
        text = re.sub(r"INJECT_KEYS = \[.*?\]", NEW_KEYS, text, count=1, flags=re.S)

    if "def main():" not in text:
        missing.append("def main()")
    else:
        text = text.replace("def main():", HELPER + "\n\ndef main():", 1)

    if SCHEMA_ANCHOR not in text:
        missing.append("SCHEMA (launch_state table)")
    else:
        text = text.replace(SCHEMA_ANCHOR, SCHEMA_ADD, 1)

    return text, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("notebooks", nargs="+")
    ap.add_argument("-o", "--out", default="patched")
    args = ap.parse_args()

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    rc = 0

    for nb_path in args.notebooks:
        p = Path(nb_path)
        nb = json.loads(p.read_text(encoding="utf-8"))
        hit = False
        for cell in nb["cells"]:
            if cell.get("cell_type") != "code":
                continue
            src = cell_text(cell)
            if "def main():" not in src or "def publish(status):" not in src:
                continue
            new, missing = patch_source(src)
            if missing:
                print(f"[FAIL] {p.name}: anchors not found -> {', '.join(missing)}", file=sys.stderr)
                rc = 1
            else:
                set_cell_text(cell, new)
                diff = "".join(difflib.unified_diff(src.splitlines(True), new.splitlines(True),
                                                    fromfile=p.name + " (original)",
                                                    tofile=p.name + " (patched)"))
                (outdir / (p.stem + ".diff.txt")).write_text(diff, encoding="utf-8")
                target = outdir / (p.stem + ".patched.ipynb")
                target.write_text(json.dumps(nb), encoding="utf-8")
                print(f"[OK] {p.name} -> {target}  (+{sum(1 for l in diff.splitlines() if l.startswith('+') and not l.startswith('+++'))} lines)")
                hit = True
        if not hit and rc == 0:
            print(f"[FAIL] {p.name}: koi cell nahi mila jisme publish()+main() ho", file=sys.stderr)
            rc = 1

    return rc


if __name__ == "__main__":
    sys.exit(main())
