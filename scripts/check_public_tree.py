"""Fail publication if tracked files include site material or common secret forms.

This is a supplemental check, not a replacement for reviewing every staged file.
Run after staging, before the first push. Uses Git's tracked-file set only.
"""

import pathlib
import re
import subprocess
import sys

root = pathlib.Path(__file__).resolve().parents[1]
paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
bad = []
pattern = re.compile(
    rb"/Users/|(?:okon\.pl|medalgora\.com)|100\.(?:90|85)\.[0-9]+\.[0-9]+"
    rb"|pcp_(?:board|agent)_[A-Za-z0-9]{24,}|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    rb"|(?:ghp_|github_pat_)[A-Za-z0-9_]{24,}"
)
for name in filter(None, paths):
    if name.startswith(("site-private/", "evidence-local/", ".env", ".venv/")) or name.endswith((".db", ".sqlite3")):
        bad.append((name, "private/generated path"))
        continue
    path = root/name
    if path.is_symlink():
        bad.append((name, "symlink"))
    elif path.is_file() and path.stat().st_size > 2_000_000:
        bad.append((name, "unexpected large file"))
    elif path.is_file() and name != "scripts/check_public_tree.py" and pattern.search(path.read_bytes()):
        bad.append((name, "possible site material or secret; inspect privately"))
if bad:
    print("Publication check failed:", bad)
    sys.exit(1)
print(f"Publication check passed for {len(list(filter(None, paths)))} tracked files; manual review still required.")
