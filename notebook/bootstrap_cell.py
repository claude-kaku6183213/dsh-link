# === DSH LINK BOOTSTRAP — Kaggle me sirf YE cell rakho, baaki code GitHub se khud aata hai ===
# A notebook ke liye SLUG = "dsh-runner-a", B ke liye "dsh-runner-b"
SLUG = "dsh-runner-a"

URL = f"https://raw.githubusercontent.com/claude-kaku6183213/dsh-link/main/notebook/patched/{SLUG}.patched.ipynb"

import json as _json, urllib.request as _url
_nb = _json.loads(_url.urlopen(URL, timeout=60).read())
for _c in _nb["cells"]:
    _src = "".join(_c["source"]) if isinstance(_c["source"], list) else _c["source"]
    exec(compile(_src, f"{SLUG}:{_c.get('id', 'cell')}", "exec"), globals())

# NOTE:
# - Secrets UI se hi aate hain (API push me nahi), isliye ye cell Kaggle editor se hi chalao.
# - Har start pe latest code GitHub se aata hai -> aage update ke liye bas GitHub pe push karo.
# - NODE_NAME patched notebook ke andar set hai (A me "A", B me "B").
