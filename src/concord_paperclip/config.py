import copy
import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path

from .engine import Engine
from .paperclip import Paperclip
from .policy import BridgeError, Principal
from .store import Store


_VERIFIER_POLICY = "verifier_seccomp_profile"


def _read_config(path, *, expected_sha256=None):
    """Open every component without following symlinks; validate the opened inode."""
    fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:-1]:
            next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        file_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(file_fd, "rb") as stream:
            mode = os.fstat(stream.fileno())
            if not stat.S_ISREG(mode.st_mode) or mode.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                raise BridgeError("UNSAFE_CONFIG")
            raw = stream.read()
            if expected_sha256 is not None and hashlib.sha256(raw).hexdigest() != expected_sha256:
                raise BridgeError("HANDOFF_CONFIG_MISMATCH")
            try:
                config = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeError):
                raise BridgeError("INVALID_CONFIG") from None
        if not isinstance(config, dict):
            raise BridgeError("INVALID_CONFIG")
        if config.get("role", "coordinator") not in ("coordinator", "worker", "reader"):
            raise BridgeError("INVALID_ROLE")
        return config, (mode.st_uid, mode.st_gid)
    except OSError:
        raise BridgeError("UNSAFE_CONFIG", "Trusted configuration unavailable or unsafe") from None
    finally:
        os.close(fd)


def _frozen_boundary(config):
    # Freeze everything except this explicitly reloadable policy. This also covers
    # future credential/authority fields without maintaining a fragile allowlist.
    return json.dumps({k: v for k, v in config.items() if k != _VERIFIER_POLICY}, sort_keys=True)


class _TrustedConfig(dict):
    def __init__(self, config, path, owner):
        super().__init__(config)
        self._origin = path
        self._owner = owner
        self._boundary = _frozen_boundary(config)

    def verifier_config(self):
        current, owner = _read_config(self._origin)
        if (owner != self._owner or _frozen_boundary(current) != self._boundary
                or _frozen_boundary(self) != self._boundary):
            raise BridgeError("CONFIG_RESTART_REQUIRED", "Trusted configuration boundary changed; restart required")
        # Never merge new credentials, commands or targets into the running server.
        result = copy.deepcopy(dict(self))
        result[_VERIFIER_POLICY] = current.get(_VERIFIER_POLICY)
        return result


def load_config(path, *, expected_sha256=None):
    # Bind only at trusted startup, never from an MCP argument or a dict key.
    origin = Path(os.path.abspath(path))
    config, owner = _read_config(origin, expected_sha256=expected_sha256)
    return _TrustedConfig(config, origin, owner)


def verifier_config(config):
    current = config.verifier_config() if isinstance(config, _TrustedConfig) else config
    policy = current.get(_VERIFIER_POLICY)
    if policy is None or policy == "":
        raise BridgeError("VERIFIER_POLICY_REQUIRED")
    if not isinstance(policy, str) or not policy.strip() or "\x00" in policy:
        raise BridgeError("INVALID_VERIFIER_POLICY")
    return current


def make_engine(config):
    token = ""
    if config.get("token_command"):
        command = config["token_command"]
        if not isinstance(command, list) or not all(isinstance(x, str) for x in command):
            raise BridgeError("INVALID_TOKEN_COMMAND")
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        if result.returncode:
            raise BridgeError("CREDENTIAL_UNAVAILABLE", "Credential command failed; output withheld")
        token = result.stdout.strip()
    elif config.get("token_file") or config.get("credential_name"):
        credential_dir = os.environ.get("CREDENTIALS_DIRECTORY")
        credential = config.get("credential_name")
        p = Path(credential_dir) / credential if credential_dir and credential else Path(config["token_file"])
        if p.is_symlink() or p.stat().st_mode & 0o077:
            raise BridgeError("UNSAFE_CREDENTIAL_FILE")
        token = p.read_text().strip()
    backend = Paperclip(config["base_url"], config["company_id"], token,
                        project_id=config.get("project_id"), run_id=os.environ.get("PAPERCLIP_RUN_ID"),
                        trusted_http_hosts=config.get("trusted_http_hosts", []))
    return Engine(Store(config["database"]), backend,
                  Principal(config["principal"], config.get("role", "coordinator"), tuple(config.get("task_ids", []))),
                  profiles=config.get("profiles", []), max_depth=config.get("max_depth", 1),
                  max_children=config.get("max_children", 2))
