"""Opt-in, trusted per-task synthetic acceptance; never reachable from model input."""

import ast
import base64
import json
import hashlib

from .policy import BridgeError
from .store import canonical


def approve(engine, config):
    engine.actor.require("coordinator")
    policies = config.get("synthetic_review", {})
    if policies.get("enabled") is not True:
        return []
    if not config.get("native_agent_id"):
        raise BridgeError("NON_MODEL_COORDINATOR_REQUIRED")
    if not isinstance(config.get("verifier_seccomp_profile"), str) or not config["verifier_seccomp_profile"]:
        raise BridgeError("VERIFIER_POLICY_REQUIRED")
    results = []
    for rule in policies.get("tasks", []):
        # Both values are known BEFORE submit; random task/run IDs are not policy inputs.
        with engine.store.connect() as c:
            operation = c.execute("SELECT task_id FROM operations WHERE owner=? AND key=? AND kind='submit'",
                                  (engine.actor.name, rule["submission_key"])).fetchone()
            if not operation:
                continue
            task_id = operation[0]
            task = engine._task(c, task_id)
            spec = json.loads(task["spec"])
            if hashlib.sha256(canonical(spec).encode()).hexdigest() != rule["spec_digest"]:
                raise BridgeError("SYNTHETIC_SPEC_MISMATCH")
            if task["state"] == "review_queued":
                queued = True
            else:
                queued = False
            if not queued and task["state"] != "review_ready":
                continue
            manifest = c.execute("SELECT * FROM manifests WHERE task_id=?", (task_id,)).fetchone()
            tests = c.execute("SELECT details FROM audit WHERE task_id=? AND event='independent_tests' "
                              "ORDER BY id DESC LIMIT 1", (task_id,)).fetchone()
            questions = c.execute("SELECT 1 FROM messages WHERE task_id=?", (task_id,)).fetchone()
        if queued:
            from .wake import wake
            results.append({"id": task_id, "executor": wake(engine, config, task_id + "-review")})
            continue
        if not manifest or not tests or questions:
            raise BridgeError("SYNTHETIC_EVIDENCE_REQUIRED")
        tests = json.loads(tests[0])
        files = json.loads(manifest["manifest"])["files"]
        paths = sorted(f["path"] for f in files)
        # Explicit expected content hashes are operator reviewed. A generated PASS
        # alone cannot enable this policy or approve arbitrary generated code.
        expected = rule["sha256"]
        if (spec["repo"] != rule["repo"] or paths != sorted(expected)
                or sorted(spec["paths"]) != paths
                or (rule.get("manifest_digest") is not None and manifest["digest"] != rule["manifest_digest"])
                or any(f["sha256"] != expected[f["path"]] for f in files)
                or sum(f["size"] for f in files) > 32768
                or not all("/" not in p and p.endswith(".py") for p in paths)
                or not any(p.startswith("test") for p in paths)
                or tests.get("status") != "passed" or tests.get("kind") != "unittest"
                or tests.get("manifest_digest") != manifest["digest"]
                or tests.get("credential_free") is not True or tests.get("network_policy") != "deny-all"
                or tests.get("seccomp") != config.get("verifier_seccomp_profile")):
            raise BridgeError("SYNTHETIC_POLICY_MISMATCH")
        allowed = {"unittest", "math", *(p[:-3] for p in paths)}
        for entry in files:
            tree = ast.parse(base64.b64decode(entry["content_base64"]).decode())
            for node in ast.walk(tree):
                modules = ([a.name for a in node.names] if isinstance(node, ast.Import)
                           else [node.module] if isinstance(node, ast.ImportFrom) else [])
                if any(m not in allowed for m in modules) or (isinstance(node, ast.ImportFrom) and node.level):
                    raise BridgeError("SYNTHETIC_STDLIB_ONLY")
        remote = engine.backend.issue(task["issue_id"])
        if remote.get("status") != "in_review":
            raise BridgeError("FORMAL_HANDOFF_REQUIRED")
        engine.review("synthetic:" + manifest["digest"], task_id, task["version"], manifest["digest"],
                      ["independent isolated stdlib unittest"], "Trusted opt-in synthetic policy",
                      machine_policy={"policy_id": rule["policy_id"], "repo": rule["repo"]})
        from .wake import wake
        results.append({"id": task_id, "digest": manifest["digest"],
                        "executor": wake(engine, config, task_id + "-review")})
    return results
