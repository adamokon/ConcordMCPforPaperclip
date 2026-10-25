"""Trusted fixed-command telemetry. Never accepts commands or paths from MCP.

The receiver only observes existing work; Paperclip still starts all model runs.
"""

import base64
import hashlib
import json
import os
import time
import uuid

from .config import verifier_config
from .policy import BridgeError, contains, relative_path, tokenish
from .store import canonical


def gateway(config, request):
    from .gateway_transport import exchange
    return exchange(config.get("gateway_command"), request,
                    os.environ.get("CREDENTIALS_DIRECTORY", ""))


def refresh_profiles(engine, config):
    from .readiness import evaluate
    result = gateway(config, {"action": "probe"})
    profiles = []
    for profile in config.get("profiles", []):
        item = dict(profile)
        probe = result.get(profile["id"], {})
        decision = evaluate(probe, time.time())
        item.update(readiness=decision, observed_status=probe.get("agent_status"), ready_until=0)
        if decision["eligible"]:
            item["ready_until"] = probe["observed_at"] + 60
        profiles.append(item)
    engine.profiles = profiles
    return [{"id": p["id"], **p["readiness"]} for p in profiles]


def import_result(engine, task_id, result, expected_seccomp=None):
    """Validate exact binding and digest again across the privileged boundary."""
    with engine.store.connect() as c:
        task = engine._task(c, task_id)
        attempt = c.execute("SELECT * FROM attempts WHERE task_id=? ORDER BY number DESC LIMIT 1",
                            (task_id,)).fetchone()
    if task["state"] == "review_ready":
        with engine.store.connect() as c:
            saved = c.execute("SELECT * FROM manifests WHERE task_id=?", (task_id,)).fetchone()
        record = result.get("snapshot", {})
        if (not saved or record.get("digest") != saved["digest"]
                or canonical(record.get("manifest")) != saved["manifest"]
                or result.get("evidence", {}).get("run_id") != attempt["run_id"]):
            raise BridgeError("RECEIPT_CONFLICT")
        return {"id": task_id, "state": "review_ready"}
    if task["state"] not in {"running", "execution_completed"} or not attempt:
        raise BridgeError("INVALID_STATE")
    evidence = result["evidence"]
    if evidence.get("status") != "succeeded" or evidence.get("environment_removed") is not True:
        raise BridgeError("INVALID_RUN_EVIDENCE")
    if attempt["run_id"] and attempt["run_id"] != evidence.get("run_id"):
        raise BridgeError("RUN_MISMATCH")
    record = result["snapshot"]
    manifest = record["manifest"]
    if evidence["issue_id"] != task["issue_id"] or evidence["agent_id"] != attempt["profile"]:
        raise BridgeError("RUN_MISMATCH")
    uuid.UUID(evidence["run_id"])
    expected = {"task_id": task_id, "issue_id": task["issue_id"],
                "run_id": evidence["run_id"], "agent_id": attempt["profile"]}
    if any(manifest.get(k) != v for k, v in expected.items()):
        raise BridgeError("RUN_MISMATCH")
    if hashlib.sha256(canonical(manifest).encode()).hexdigest() != record["digest"]:
        raise BridgeError("MANIFEST_MISMATCH")
    spec = json.loads(task["spec"])
    files = manifest["files"]
    if not isinstance(files, list) or not 1 <= len(files) <= 128:
        raise BridgeError("INVALID_ARTIFACT_LIST")
    paths, total, question = set(), 0, None
    for f in files:
        path = relative_path(f["path"])
        if path in paths or (path != "bridge_question.json" and not any(
                contains(scope, path) for scope in spec["paths"])):
            raise BridgeError("ARTIFACT_OUTSIDE_SCOPE")
        paths.add(path)
        data = base64.b64decode(f["content_base64"], validate=True)
        total += len(data)
        if len(data) > 262144 or total > 1048576 or len(data) != f["size"]:
            raise BridgeError("ARTIFACT_LIMIT")
        if hashlib.sha256(data).hexdigest() != f["sha256"] or tokenish(data):
            raise BridgeError("UNSAFE_ARTIFACT")
        if path == "bridge_question.json":
            parsed = json.loads(data)
            question = parsed.get("question") if isinstance(parsed, dict) else None
            if not isinstance(question, str) or not 1 <= len(question) <= 8000:
                raise BridgeError("INVALID_QUESTION")
    tests = result.get("tests", {})
    # These are independent sandbox results, never a model's RESULT.txt claim.
    if (tests.get("manifest_digest") != record["digest"] or tests.get("status") not in {"passed", "failed"}
            or tests.get("credential_free") is not True or tests.get("network_policy") != "deny-all"):
        raise BridgeError("INDEPENDENT_TESTS_REQUIRED")
    if expected_seccomp is not None and tests.get("seccomp") != expected_seccomp:
        raise BridgeError("VERIFIER_POLICY_MISMATCH")
    if task["state"] == "running":
        engine.observe(task_id, evidence)
    with engine.store.transaction() as c:
        current = engine._task(c, task_id)
        if result.get("native_review_required") is True:
            engine.store.audit(c, engine.actor.name, task_id, "native_review_required")
        if current["state"] == "review_ready":
            saved = c.execute("SELECT digest,manifest FROM manifests WHERE task_id=?", (task_id,)).fetchone()
            if not saved or saved["digest"] != record["digest"] or saved["manifest"] != canonical(manifest):
                raise BridgeError("RECEIPT_CONFLICT")
            return {"id": task_id, "state": "review_ready"}
        if current["state"] != "execution_completed":
            raise BridgeError("STALE_VERSION")
        c.execute("INSERT OR REPLACE INTO manifests VALUES(?,?,?)",
                  (task_id, record["digest"], canonical(manifest)))
        state = "review_ready" if tests["status"] == "passed" else "verification_failed"
        engine._set(c, task_id, state)
        engine.store.audit(c, engine.actor.name, task_id, "independent_tests", tests)
        if question and state == "review_ready":
            message_id = str(uuid.uuid5(uuid.UUID(evidence["run_id"]), "bridge-question"))
            c.execute("INSERT OR IGNORE INTO messages(id,task_id,sender,recipient,body,created) VALUES(?,?,?,?,?,?)",
                      (message_id, task_id, attempt["profile"], task["owner"], question, time.time()))
            engine.store.audit(c, engine.actor.name, task_id, "question_received", {"id": message_id})
    return {"id": task_id, "state": state, "digest": record["digest"], "tests": tests}


def receive(engine, config):
    engine.actor.require("coordinator")
    config = verifier_config(config)
    with engine.store.connect() as c:
        tasks = [r[0] for r in c.execute("SELECT id FROM tasks WHERE state IN ('running','execution_completed')")]
    results = []
    for task_id in tasks:
        try:
            result = gateway(config, {"action": "receive", "task_id": task_id})
            if result.get("pending"):
                results.append({"id": task_id, "state": "pending"})
            elif result.get("failure") in {"failed", "cancelled", "timed_out"}:
                if result.get("evidence", {}).get("status") != result["failure"]:
                    raise BridgeError("INVALID_RUN_EVIDENCE")
                engine.observe(task_id, result["evidence"])
                with engine.store.transaction() as c:
                    engine._set(c, task_id, "execution_failed")
                results.append({"id": task_id, "state": "execution_failed", "status": result["failure"]})
            else:
                results.append(import_result(engine, task_id, result, config["verifier_seccomp_profile"]))
        except (BridgeError, ValueError, KeyError, TypeError) as e:
            results.append({"id": task_id, "code": getattr(e, "code", "INVALID_RECEIPT")})
    return results
