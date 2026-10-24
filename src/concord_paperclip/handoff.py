"""Operator-only resumption of a supervisor-attested initialized stdio connection.

This is not a fresh client handshake. Never register this entrypoint as an MCP tool.
"""

import json
import math
import os
import re
import socket
import stat
import time
from pathlib import Path

from mcp.server.stdio import stdio_server

from .config import load_config, make_engine
from .policy import BridgeError
from .server import build_server


_FIELDS = {"schema_version", "initialized", "unit", "uid", "config_sha256", "stdin", "stdout", "expires_at"}
_FD_FIELDS = {"dev", "ino", "type"}


def _invalid():
    return BridgeError("INVALID_HANDOFF", "Initialized stdio handoff validation failed")


def _read_attestation(filename):
    """Bounded, nonblocking read; no symlinks in any component, including parents."""
    if not isinstance(filename, str) or not filename or "\x00" in filename:
        raise _invalid()
    path = Path(os.path.abspath(filename))
    directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:-1]:
            next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = next_fd
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0
                    or metadata.st_mode & 0o022 or metadata.st_size > 8192):
                raise _invalid()
            raw = stream.read(8193)
            if len(raw) > 8192:
                raise _invalid()
        return json.loads(raw, object_pairs_hook=_unique_keys)
    except (OSError, ValueError, UnicodeError, RecursionError):
        raise _invalid() from None
    finally:
        os.close(directory)


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate key")
        result[key] = value
    return result


def _current_cgroups():
    # Kernel source only: neither environment variables nor a caller assertion.
    return Path("/proc/self/cgroup").read_text().splitlines()


def _is_unix_socket(number):
    duplicate = os.dup(number)
    try:
        connection = socket.socket(fileno=duplicate)
    except OSError:
        os.close(duplicate)
        raise
    with connection:
        return connection.family == socket.AF_UNIX


def _validate(attestation):
    if not isinstance(attestation, dict) or set(attestation) != _FIELDS:
        raise _invalid()
    a = attestation
    if type(a["schema_version"]) is not int or a["schema_version"] != 1 or a["initialized"] is not True:
        raise _invalid()
    unit = a["unit"]
    if not isinstance(unit, str) or unit in (".", "..") or not re.fullmatch(r"[A-Za-z0-9_.:@\\-]+", unit):
        raise _invalid()
    if type(a["uid"]) is not int or a["uid"] < 0 or a["uid"] != os.geteuid():
        raise _invalid()
    digest = a["config_sha256"]
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
        raise _invalid()
    expiry = a["expires_at"]
    now = time.time()
    if type(expiry) not in (int, float) or not math.isfinite(expiry) or not now < expiry <= now + 120:
        raise _invalid()
    for number, key in [(0, "stdin"), (1, "stdout")]:
        expected = a[key]
        if (not isinstance(expected, dict) or set(expected) != _FD_FIELDS
                or any(type(expected[k]) is not int or expected[k] < 0 for k in _FD_FIELDS)
                or expected["type"] not in (stat.S_IFIFO, stat.S_IFSOCK)):
            raise _invalid()
        if expected["type"] == stat.S_IFSOCK and not _is_unix_socket(number):
            raise _invalid()
        actual = os.fstat(number)
        if expected != {"dev": actual.st_dev, "ino": actual.st_ino, "type": stat.S_IFMT(actual.st_mode)}:
            raise _invalid()
    paths = [line.split(":", 2)[2] for line in _current_cgroups() if len(line.split(":", 2)) == 3]
    if not any(path.endswith("/" + unit) for path in paths):
        raise _invalid()
    return digest.lower()


def validate_handoff(config_path, attestation_path):
    """Return normal trusted config only after all runtime assertions are checked."""
    try:
        digest = _validate(_read_attestation(attestation_path))
        return load_config(config_path, expected_sha256=digest)
    except (OSError, ValueError, OverflowError):
        raise _invalid() from None


async def resume_stdio(config_path, attestation_path):
    config = validate_handoff(config_path, attestation_path)
    server = build_server(make_engine(config), config)
    # Official SDK dispatch represents the already initialized logical connection.
    # No input/output or credential/backend work occurs before validation succeeds.
    async with stdio_server() as (read, write):
        await server._mcp_server.run(read, write, server._mcp_server.create_initialization_options(),
                                     stateless=True)
