"""Privileged host gateway behind a dedicated forced-command SSH account.

Only probe and receive(task UUID) are accepted. All paths, profiles, containers
and executable commands come from root-owned config or the coordinator journal.
No model task execution, shell strings, credentials or raw worker logs returned.
"""

import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .policy import BridgeError
from .sandbox import NAMESPACE, namespace_policy, resources
from .store import canonical


def call(command, request=None, timeout=25):
    p = subprocess.run(command, input=canonical(request).encode() if request is not None else None,
                       capture_output=True, timeout=timeout)
    if p.returncode or len(p.stdout) > 2_000_000:
        raise BridgeError("GATEWAY_COMMAND_FAILED")
    return json.loads(p.stdout)


def worker(config, request):
    value = call(config["worker_command"], request)
    if not value.get("ok"):
        raise BridgeError(value.get("code", "WORKER_IO_FAILURE"))
    return value["result"]


def verify(config, record, control_label=None):
    """Adopt only deterministic, content-matching resources after interruption."""
    root = Path(config["receipt_root"])
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    digest = record["digest"]
    policy = hashlib.sha256(canonical({"image": config["test_image"], "node": config["node_selector"],
                                      "runner": "v3", "seccomp": config["test_seccomp_profile"],
                                      "label": control_label}).encode()).hexdigest()[:16]
    cache = root / (digest + "-" + policy + ".json")
    if cache.exists():
        result = json.loads(cache.read_text())
        cleanup(config["kubectl_command"], result["job"])
        return result
    command = config["kubectl_command"]
    name, cm, job = resources(record, config["test_image"], config["node_selector"], policy,
                              control_label or "concord-verifier", config["test_seccomp_profile"])
    for obj in namespace_policy():
        call_apply(command, obj)
    # A ConfigMap is immutable; matching its data before adopting a Job is required.
    for kind, obj in (("configmap", cm), ("job", job)):
        p = subprocess.run(command + ["get", kind, name, "-n", NAMESPACE, "-o", "json", "--ignore-not-found"],
                           capture_output=True, timeout=15)
        if p.returncode:
            raise BridgeError("SANDBOX_QUERY_FAILED")
        if p.stdout.strip():
            old = json.loads(p.stdout)
            if kind == "configmap":
                matches = old.get("data") == obj["data"] and old.get("immutable") is True
            else:
                old_spec = old.get("spec", {}).get("template", {}).get("spec", {})
                expected = obj["spec"]["template"]["spec"]
                matches = all(old_spec.get(k) == v for k, v in expected.items()
                              if k not in {"containers", "volumes", "tolerations"})
                # API defaults add nested fields. Compare the security-relevant
                # generated command/image/mounts and every explicitly set limit.
                old_c = old_spec.get("containers", [{}])[0]
                new_c = expected["containers"][0]
                matches = matches and subset(new_c, old_c)
                matches = matches and old_spec.get("volumes", [{}])[0].get("configMap", {}).get("name") == name
                matches = matches and len(old_spec.get("volumes", [])) == 2
                matches = matches and subset(expected["volumes"], old_spec.get("volumes"))
            if not matches:
                raise BridgeError("SANDBOX_RESOURCE_CONFLICT")
        else:
            p = subprocess.run(command + ["create", "-f", "-"], input=canonical(obj).encode(),
                               capture_output=True, timeout=15)
            if p.returncode:
                raise BridgeError("SANDBOX_CREATE_UNCERTAIN")
    deadline = time.monotonic() + 72
    while time.monotonic() < deadline:
        observed = call(command + ["get", "job", name, "-n", NAMESPACE, "-o", "json"])
        status = observed.get("status", {})
        if status.get("succeeded") or status.get("failed"):
            break
        time.sleep(1)
    else:
        raise BridgeError("SANDBOX_PENDING")
    passed = bool(status.get("succeeded"))
    # Store no stdout/stderr from generated code. Exit status is an independent
    # execution result, not a guarantee that generated tests are comprehensive.
    result = {"manifest_digest": digest, "status": "passed" if passed else "failed",
              "credential_free": True, "network_policy": "deny-all", "job": name,
              "observed_at": time.time(), "image": config["test_image"]}
    result["seccomp"] = config["test_seccomp_profile"] if not control_label else "RuntimeDefault"
    result["kind"] = ("unittest" if any(f["path"].startswith("test") and f["path"].endswith(".py")
                     for f in record["manifest"]["files"]) else "clarification_validation")
    if control_label:
        result["network_policy"] = "operator-positive-control"
    temporary = cache.with_suffix(".tmp")
    temporary.write_text(canonical(result))
    os.replace(temporary, cache)
    cleanup(command, name)
    return result


def cleanup(command, name):
    p = subprocess.run(command + ["delete", "job/" + name, "configmap/" + name, "-n", NAMESPACE,
                                   "--ignore-not-found", "--wait=true", "--timeout=10s"],
                       capture_output=True, timeout=15)
    if p.returncode:
        raise BridgeError("SANDBOX_CLEANUP_PENDING")


def subset(expected, observed):
    if isinstance(expected, dict):
        return isinstance(observed, dict) and all(k in observed and subset(v, observed[k])
                                                  for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(observed, list) and len(expected) == len(observed) and all(
            subset(a, b) for a, b in zip(expected, observed, strict=True))
    return expected == observed


def call_apply(command, obj):
    p = subprocess.run(command + ["apply", "-f", "-"], input=canonical(obj).encode(),
                       capture_output=True, timeout=15)
    if p.returncode:
        raise BridgeError("SANDBOX_POLICY_FAILED")


def execute(config, request):
    if not isinstance(request, dict):
        raise BridgeError("INVALID_REQUEST")
    if request == {"action": "probe"}:
        roster = call(config["telemetry_command"], {"action": "probe"})
        result = {}
        for agent in roster:
            identity = agent["id"]
            if identity not in config["profiles"]:
                continue
            probe = worker(config, {"action": "probe", "profile": config["profiles"][identity]})
            result[identity] = {**probe, "observed_at": time.time(), "agent_status": agent["status"],
                               "adapter_type": agent["adapterType"], "active_runs": agent["active_runs"],
                               "provider_auth": "unknown", "provider_quota": "unknown"}
        return result
    if set(request) != {"action", "task_id"} or request["action"] != "receive":
        raise BridgeError("INVALID_REQUEST")
    task_id = str(uuid.UUID(request["task_id"]))
    context = call(config["context_command"] + ["--task", task_id])
    if context["state"] not in {"running", "execution_completed"}:
        raise BridgeError("INVALID_STATE")
    identity = context["profile"]
    profile = config["profiles"][identity]
    run = call(config["telemetry_command"], {"action": "run", "issue_id": context["issue_id"],
               "agent_id": identity, "after": context["created"]})
    if not run or run["status"] not in {"succeeded", "failed", "cancelled", "timed_out"}:
        return {"pending": True}
    if context["run_id"] and context["run_id"] != run["id"]:
        raise BridgeError("RUN_MISMATCH")
    binding = {"task_id": task_id, "issue_id": context["issue_id"], "run_id": run["id"], "agent_id": identity}
    evidence = {"issue_id": context["issue_id"], "agent_id": identity, "run_id": run["id"],
                "status": run["status"], "environment_removed": True}
    if run["status"] != "succeeded":
        cleaned = worker(config, {"action": "check", "profile": profile, "run_id": run["id"]})
        return cleaned if cleaned.get("pending") else {"evidence": evidence, "failure": run["status"]}
    output = worker(config, {"action": "collect", "profile": profile, "run_id": run["id"],
                            "paths": context["paths"], "context": binding})
    if output.get("pending"):
        return output
    record = output["snapshot"]
    if hashlib.sha256(canonical(record["manifest"]).encode()).hexdigest() != record["digest"]:
        raise BridgeError("MANIFEST_MISMATCH")
    evidence["environment_removed"] = output["environment_removed"]
    return {"evidence": evidence,
            "snapshot": record, "tests": verify(config, record)}


def main():
    os.umask(0o077)
    try:
        config = json.loads(Path(sys.argv[1]).read_text())
        raw = sys.stdin.buffer.read(4097)
        if len(raw) > 4096:
            raise BridgeError("REQUEST_TOO_LARGE")
        # Serializes sandbox adoption and receipt cache writes across receivers.
        import fcntl
        with open(config["lock_file"], "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = execute(config, json.loads(raw))
        print(canonical({"ok": True, "result": result}))
    except Exception as e:
        print(canonical({"ok": False, "code": getattr(e, "code", "GATEWAY_FAILURE")}))


if __name__ == "__main__":
    main()
