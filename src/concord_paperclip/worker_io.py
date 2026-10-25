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
    if not isinstance(request, dict) or request.get("action") not in {"probe", "collect", "check", "preflight", "partial"}:
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
    if request["action"] == "preflight":
        # No absent-files heuristic: this fact is only one prerequisite for a
        # separately authenticated fixed-adapter pre-provider attestation.
        if request["run_id"] != run_id:
            raise BridgeError("INVALID_RUN_ID")
        return {"environment_removed": True, "workspace_absent": not os.path.lexists(root)}
    if request["action"] == "partial":
        import base64
        import re
        from .partial_io import capture_partial
        from .partial_result import classify_partial
        def private_file(name, max_file=262144):
            item = snapshot(root, [name], [name], {}, max_file=max_file, max_total=2097152)
            return base64.b64decode(item['manifest']['files'][0]['content_base64']).decode('utf-8')
        raw = json.loads(private_file('result.json'))
        cli = json.loads(private_file('cli-output.json', 2097152))
        stderr = private_file('cli-stderr.log')
        error = stderr + ' ' + str(cli.get('error', ''))
        response = next((cli[k] for k in ('response', 'result', 'text') if k in cli), None)
        if isinstance(response, dict) and set(response) == {'text'}:
            response = response['text']
        present = [p for p in request['paths'] if os.path.lexists(root / p)]
        facts = dict(run_id=raw.get('run_id'), expected_run_id=run_id,
            worker_status=raw.get('status'),worker_exit_code=raw.get('exit_code'),
            worker_denied_actions=raw.get('denied_actions'),elapsed_seconds=raw.get('elapsed_seconds'),
            deadline_seconds=request['deadline_seconds'],timeout_observed=bool(re.search(r'(?i)timeout|timed out|deadline',error)),
            provider_stopped=True,environment_removed=True,producer_verified=request['producer_verified'],
            auth_error=bool(re.search(r'(?i)unauthorized|invalid.token|invalid.grant|oauth.*fail|HTTP 40[13]',error)),
            quota_error=bool(re.search(r'(?i)quota.exceeded|RESOURCE_EXHAUSTED|rate.limit.exceeded|HTTP.429|too.many.requests',error)),
            security_error=raw.get('denied_actions')!=[],task_cancelled=request['task_cancelled'],
            file_count=len(present),allowed_scope=True,native_status=request['native_status'],
            cli_status=cli.get('status'),cli_response_empty=isinstance(response,str) and not response.strip(),
            outer_timeout=raw.get('result')=='Bounded task execution timed out')
        decision=classify_partial(facts)
        if decision['eligible'] is not True:
            raise BridgeError('PARTIAL_INELIGIBLE', decision['code'])
        return capture_partial(root, request['paths'], request['context'])
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
