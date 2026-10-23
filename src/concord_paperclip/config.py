import json
import os
import stat
import subprocess
from pathlib import Path

from .engine import Engine
from .paperclip import Paperclip
from .policy import BridgeError, Principal
from .store import Store


def load_config(path):
    p = Path(path)
    mode = p.stat()
    if p.is_symlink() or mode.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise BridgeError("UNSAFE_CONFIG")
    config = json.loads(p.read_text())
    role = config.get("role", "coordinator")
    if role not in {"coordinator", "worker", "reader"}:
        raise BridgeError("INVALID_ROLE")
    return config


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
