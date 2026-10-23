"""Snapshot allowlisted regular files using pinned directory FDs and O_NOFOLLOW."""

import base64
import hashlib
import json
import os
import stat
from contextlib import contextmanager
from pathlib import Path

from .policy import BridgeError, contains, relative_path, tokenish
from .store import canonical


@contextmanager
def directory_fd(path):
    path = Path(path).absolute()
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = new
        yield fd
    finally:
        os.close(fd)


def snapshot(root, paths, allowed_scopes, context, max_file=262144, max_total=1048576):
    if not isinstance(paths, list) or not 1 <= len(paths) <= 128 or len(set(paths)) != len(paths):
        raise BridgeError("INVALID_ARTIFACT_LIST")
    files = []
    total = 0
    try:
        with directory_fd(root) as root_fd:
            for path in sorted(paths):
                relative_path(path)
                if path.endswith("/") or not any(contains(scope, path) for scope in allowed_scopes):
                    raise BridgeError("ARTIFACT_OUTSIDE_SCOPE")
                fd = os.dup(root_fd)
                try:
                    parts = path.split("/")
                    for part in parts[:-1]:
                        new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                        os.close(fd)
                        fd = new
                    # NONBLOCK prevents waiting on a FIFO before fstat can reject it.
                    source = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                    try:
                        before = os.fstat(source)
                        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > max_file:
                            raise BridgeError("UNSAFE_ARTIFACT")
                        with os.fdopen(source, "rb", closefd=False) as stream:
                            data = stream.read(max_file + 1)
                        after = os.fstat(source)
                        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                            after.st_size, after.st_mtime_ns, after.st_ctime_ns
                        ) or len(data) != after.st_size or len(data) > max_file:
                            raise BridgeError("ARTIFACT_CHANGED")
                    finally:
                        os.close(source)
                finally:
                    os.close(fd)
                total += len(data)
                if total > max_total:
                    raise BridgeError("ARTIFACT_LIMIT")
                if tokenish(data):
                    raise BridgeError("POSSIBLE_SECRET")
                files.append({"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                              "content_base64": base64.b64encode(data).decode()})
    except OSError:
        raise BridgeError("UNSAFE_ARTIFACT", "Missing, inaccessible, special or symlinked path") from None
    manifest = {"schema_version": 1, **context, "files": files}
    digest = hashlib.sha256(canonical(manifest).encode()).hexdigest()
    return {"digest": digest, "manifest": manifest}


def public_manifest(record):
    result = json.loads(canonical(record))
    for entry in result["manifest"]["files"]:
        entry.pop("content_base64", None)
    return result
