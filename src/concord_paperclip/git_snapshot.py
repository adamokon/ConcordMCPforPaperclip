"""Operator-side export of immutable Git objects; never runs checkout hooks."""

import argparse
import base64
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys

from .source_snapshot import MAX_CONTENT_SIZE, MAX_ENTRIES, MAX_TOTAL_CONTENT, SnapshotError, encode_snapshot


def export_commit(repository, commit):
    """Export a full SHA-1 commit, not a branch or the possibly dirty worktree.

    This is an operator tool: repository selection and public-data review precede
    export. Git filters, submodules and LFS downloads are deliberately not run.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SnapshotError("A full immutable SHA-1 commit is required")
    repository = Path(repository).resolve(strict=True)
    env = {"PATH": "/usr/bin:/bin", "HOME": "/var/empty", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_NO_REPLACE_OBJECTS": "1", "GIT_TERMINAL_PROMPT": "0"}

    def git(*args):
        return subprocess.check_output(["/usr/bin/git", "-C", str(repository), *args],
                                       env=env, cwd="/", timeout=60)

    if git("cat-file", "-t", commit).strip() != b"commit":
        raise SnapshotError("Source object is not a commit")
    rows = git("ls-tree", "-r", "-z", "--full-tree", commit).split(b"\0")
    if len(rows) - 1 > MAX_ENTRIES:
        raise SnapshotError("Too many source entries")
    entries, total = [], 0
    for row in rows:
        if not row:
            continue
        header, name = row.split(b"\t", 1)
        mode, kind, oid = header.decode("ascii").split()
        if kind != "blob" or mode not in ("100644", "100755", "120000"):
            raise SnapshotError("Unsupported Git entry: submodules need separate pinned snapshots")
        size = int(git("cat-file", "-s", oid))
        total += size
        if size > MAX_CONTENT_SIZE or total > MAX_TOTAL_CONTENT:
            raise SnapshotError("Git source exceeds snapshot content limits")
        content = git("cat-file", "blob", oid)
        actual = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        if len(content) != size or actual != oid:
            raise SnapshotError("Git blob integrity mismatch")
        if content.startswith(b"version https://git-lfs.github.com/spec/v1\n"):
            raise SnapshotError("LFS pointers are not complete source artifacts")
        entries.append(dict(path=name.decode("utf-8"), mode=mode,
                            kind="symlink" if mode == "120000" else "file",
                            content_base64=base64.b64encode(content).decode("ascii"),
                            sha256=hashlib.sha256(content).hexdigest()))
    return encode_snapshot(commit, entries)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    raw = export_commit(args.repository, args.commit)
    # Refuse accidental replacement of another source artifact.
    with open(args.output, "xb") as stream:
        stream.write(raw)
    print(hashlib.sha256(raw).hexdigest(), file=sys.stderr)


if __name__ == "__main__":
    main()
