"""Read-only worker-side helper invoked by an operator-owned fixed gateway."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

from .artifacts import snapshot
from .policy import BridgeError


def execute(config, request):
    if not isinstance(request, dict) or request.get("action") not in {"probe", "collect", "check"}:
        raise BridgeError("INVALID_REQUEST")
    profile = config["profiles"][request["profile"]]
    home = Path(profile["home"])
    command = [config["kubectl"], "--kubeconfig", profile["kubeconfig"],
               "get", "jobs,pods", "-n", profile["namespace"], "-o", "json"]
    p = subprocess.run(command, capture_output=True, timeout=15)
    if p.returncode:
        raise BridgeError("ENVIRONMENT_UNKNOWN")
    items = json.loads(p.stdout)["items"]
    if request["action"] == "probe":
        oauth = home / ".gemini/antigravity-cli/antigravity-oauth-token"
        try:
            s = oauth.lstat()
            present = stat.S_ISREG(s.st_mode) and s.st_uid == 1000 and not s.st_mode & 0o077
        except FileNotFoundError:
            present = False
        enrolled = profile.get("legacy_enrolled", False)
        if profile.get("enrollment_file"):
            enrolled = json.loads(Path(profile["enrollment_file"]).read_text()).get("enrolled") is True
        return {"environment_empty": not items, "enrolled": enrolled, "oauth_present": present}
    import uuid
    run_id = str(uuid.UUID(request["run_id"]))
    # Any residual environment for this run blocks receipt, even a terminated pod.
    for item in items:
        if item.get("metadata", {}).get("labels", {}).get("agy.binzoo.io/run-id") == run_id:
            return {"pending": True}
    if request["action"] == "check":
        return {"environment_removed": True}
    root = home / "workspaces" / run_id
    state = snapshot(root, ["result.json"], ["result.json"], {})
    import base64
    result = json.loads(base64.b64decode(state["manifest"]["files"][0]["content_base64"]))
    if result.get("run_id") != run_id or result.get("denied_actions") != []:
        raise BridgeError("WORKER_RESULT_REJECTED")
    if result.get("status") != "success" or result.get("exit_code") != 0:
        raise BridgeError("WORKER_FAILED")
    paths = request["paths"]
    if any(p.endswith("/") for p in paths):
        raise BridgeError("AUTOMATIC_RECEIPT_REQUIRES_EXACT_PATHS")
    allowed = list(dict.fromkeys(paths + ["bridge_question.json"]))
    if (root / "bridge_question.json").exists():
        paths = [p for p in allowed if (root / p).exists()]
    else:
        paths = [p for p in paths if p != "bridge_question.json"]
    return {"snapshot": snapshot(root, paths, allowed, request["context"]),
            "environment_removed": True}


def main():
    os.umask(0o077)
    try:
        config = json.loads(Path(sys.argv[1]).read_text())
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise BridgeError("REQUEST_TOO_LARGE")
        result = execute(config, json.loads(raw))
        print(json.dumps({"ok": True, "result": result}))
    except Exception as e:
        print(json.dumps({"ok": False, "code": getattr(e, "code", "WORKER_IO_FAILURE")}))


if __name__ == "__main__":
    main()
