"""Local Unix broker. No shell, arbitrary paths, public port or caller-selected operation.

Only a platform-authenticated *currently running* native coordinator run can
drain the already-validated journal. The model never receives the persistent key.
"""

import json
import os
import socket
import socketserver
import stat
from pathlib import Path

from .native import execute
from .policy import BridgeError

MAX_REQUEST = 32768


def serve(config, path, group_id):
    path = Path(path)
    if path.exists():
        if not stat.S_ISSOCK(path.lstat().st_mode):
            raise BridgeError("UNSAFE_SOCKET_PATH")
        # Never unlink a live broker socket. Replacement is permitted only if
        # the old listener is verifiably gone (e.g. after process termination).
        with socket.socket(socket.AF_UNIX) as probe:
            try:
                probe.connect(str(path))
            except ConnectionRefusedError:
                path.unlink()
            else:
                raise BridgeError("BROKER_ALREADY_RUNNING")

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.request.settimeout(10)
            try:
                raw = self.rfile.readline(MAX_REQUEST+1)
                if len(raw) > MAX_REQUEST or not raw.endswith(b"\n"):
                    raise BridgeError("REQUEST_TOO_LARGE")
                request = json.loads(raw)
                if set(request) != {"run_id", "runtime_token"}:
                    raise BridgeError("INVALID_REQUEST")
                if not all(isinstance(v, str) and 1 <= len(v) <= 16384 for v in request.values()):
                    raise BridgeError("INVALID_REQUEST")
                result = execute(config, request["run_id"], request["runtime_token"])
                result = {"ok": True, "result": result}
            except BridgeError as e:
                result = {"ok": False, "code": e.code}
            except Exception:
                result = {"ok": False, "code": "BROKER_FAILURE"}
            self.wfile.write(json.dumps(result).encode()+b"\n")

    with socketserver.UnixStreamServer(str(path), Handler) as server:
        os.chown(path, os.getuid(), group_id)
        os.chmod(path, 0o660)
        server.serve_forever(poll_interval=0.5)


def request_native(path):
    run_id = os.environ.get("PAPERCLIP_RUN_ID")
    token = os.environ.get("PAPERCLIP_API_KEY")
    if not run_id or not token:
        raise BridgeError("NATIVE_CONTEXT_REQUIRED")
    payload = json.dumps({"run_id": run_id, "runtime_token": token}).encode()+b"\n"
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(100)
        client.connect(str(path))
        client.sendall(payload)
        with client.makefile("rb") as stream:
            result = json.loads(stream.readline(262145))
    if not result.get("ok"):
        raise BridgeError(result.get("code", "BROKER_FAILURE"))
    return result["result"]
