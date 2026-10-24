"""Forced-command remote verifier: snapshot JSON in, independent tests JSON out."""

import base64
import hashlib
import json
import os
import sys

from .config import load_config, require_root_config
from .gateway import verify
from .policy import BridgeError, relative_path, tokenish
from .store import canonical


def validate(record):
    manifest = record["manifest"]
    if hashlib.sha256(canonical(manifest).encode()).hexdigest() != record["digest"]:
        raise BridgeError("MANIFEST_MISMATCH")
    files = manifest["files"]
    if not isinstance(files, list) or not 1 <= len(files) <= 128:
        raise BridgeError("ARTIFACT_LIMIT")
    paths, total = set(), 0
    for entry in files:
        path = relative_path(entry["path"])
        data = base64.b64decode(entry["content_base64"], validate=True)
        total += len(data)
        if (path in paths or len(data) > 262144 or total > 1048576 or len(data) != entry["size"]
                or hashlib.sha256(data).hexdigest() != entry["sha256"] or tokenish(data)):
            raise BridgeError("UNSAFE_ARTIFACT")
        paths.add(path)
    return record


def main():
    os.umask(0o077)
    try:
        require_root_config(sys.argv[1])
        config = load_config(sys.argv[1])
        raw = sys.stdin.buffer.read(2_000_001)
        if len(raw) > 2_000_000:
            raise BridgeError("ARTIFACT_LIMIT")
        record = validate(json.loads(raw))
        import fcntl
        with open(config["lock_file"], "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = verify(config, record)
        print(canonical(result))
    except Exception as error:
        print(getattr(error, "code", "VERIFIER_FAILED"), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
