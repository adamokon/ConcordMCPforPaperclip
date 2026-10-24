import base64
import copy
import hashlib
import json
import uuid

import pytest

from concord_paperclip.automation import import_result
from concord_paperclip.policy import BridgeError
from concord_paperclip.sandbox import namespace_policy, resources
from concord_paperclip.store import canonical
from conftest import running


def receipt(engine, backend):
    task = running(engine)
    run_id = str(uuid.uuid4())
    data = b"print('public synthetic artifact')\n"
    manifest = {"schema_version": 1, "task_id": task["id"], "issue_id": task["issue_id"],
                "run_id": run_id, "agent_id": backend.profile, "files": [{"path": "main.py", "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(), "content_base64": base64.b64encode(data).decode()}]}
    digest = hashlib.sha256(canonical(manifest).encode()).hexdigest()
    return task, {"snapshot": {"digest": digest, "manifest": manifest},
                  "evidence": {"issue_id": task["issue_id"], "agent_id": backend.profile, "run_id": run_id,
                               "status": "succeeded", "environment_removed": True},
                  "tests": {"manifest_digest": digest, "status": "passed", "credential_free": True,
                            "network_policy": "deny-all"}}


def test_receiver_idempotent_and_does_not_close_or_dispatch(setup):
    engine, backend, store = setup
    task, result = receipt(engine, backend)
    patches = backend.patches
    assert import_result(engine, task["id"], result)["state"] == "review_ready"
    assert import_result(engine, task["id"], result)["state"] == "review_ready"
    assert backend.patches == patches
    assert backend.issue(task["issue_id"])["status"] == "todo"
    with store.connect() as c:
        assert c.execute("SELECT count(*) FROM audit WHERE event='independent_tests'").fetchone()[0] == 1


@pytest.mark.parametrize("change,code", [
    (lambda r: r["evidence"].update(agent_id=str(uuid.uuid4())), "RUN_MISMATCH"),
    (lambda r: r["evidence"].update(environment_removed=False), "INVALID_RUN_EVIDENCE"),
    (lambda r: r["snapshot"].update(digest="0"*64), "MANIFEST_MISMATCH"),
    (lambda r: r["tests"].update(credential_free=False), "INDEPENDENT_TESTS_REQUIRED"),
    (lambda r: r["tests"].update(manifest_digest="other"), "INDEPENDENT_TESTS_REQUIRED"),
])
def test_receiver_rejects_untrusted_or_misbound_results(setup, change, code):
    engine, backend, _ = setup
    task, result = receipt(engine, backend)
    change(result)
    with pytest.raises(BridgeError, match=code):
        import_result(engine, task["id"], result)
    assert engine.inspect(task["id"])["state"] == "running"


def test_receiver_checks_content_not_just_manifest_hash(setup):
    engine, backend, _ = setup
    task, result = receipt(engine, backend)
    result["snapshot"]["manifest"]["files"][0]["sha256"] = "0"*64
    digest = hashlib.sha256(canonical(result["snapshot"]["manifest"]).encode()).hexdigest()
    result["snapshot"]["digest"] = result["tests"]["manifest_digest"] = digest
    with pytest.raises(BridgeError, match="UNSAFE_ARTIFACT"):
        import_result(engine, task["id"], result)


def test_failed_verification_retains_claims_but_releases_cleaned_worker_slot(setup):
    engine, backend, store = setup
    task, result = receipt(engine, backend)
    result["tests"]["status"] = "failed"
    with pytest.raises(BridgeError, match="VERIFIER_POLICY_MISMATCH"):
        import_result(engine, task["id"], result, "required-profile.json")
    result["tests"]["seccomp"] = "required-profile.json"
    assert import_result(engine, task["id"], result, "required-profile.json")["state"] == "verification_failed"
    with store.connect() as c:
        assert c.execute("SELECT state FROM attempts").fetchone()[0] == "terminal"
        assert c.execute("SELECT count(*) FROM claims").fetchone()[0] > 0


def test_sandbox_has_no_credentials_or_host_volumes():
    record = {"digest": "a"*64, "manifest": {"files": [{"path": "test_public.py", "content_base64":
              base64.b64encode(b"import unittest\n").decode()}]}}
    _, cm, job = resources(record, "example.invalid/public-test@sha256:" + "b"*64, {"worker": "test"}, "v1")
    pod = job["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert not pod["hostNetwork"] and not pod["hostPID"]
    assert all(set(v) <= {"name", "configMap", "emptyDir"} for v in pod["volumes"])
    assert pod["containers"][0]["securityContext"]["readOnlyRootFilesystem"]
    assert pod["containers"][0]["securityContext"]["seccompProfile"]["type"] == "Localhost"
    assert pod["containers"][0]["env"] == [{"name": "HOME", "value": "/tmp"}]
    assert cm["immutable"]
    policy = namespace_policy()[1]["spec"]
    assert policy["ingress"] == policy["egress"] == []
    assert set(policy["policyTypes"]) == {"Ingress", "Egress"}
    assert not any("secret" in v or "projected" in v for v in pod["volumes"])


def test_sandbox_does_not_accept_nested_or_missing_tests():
    record = {"digest": "a"*64, "manifest": {"files": [{"path": "dir/test_x.py"}]}}
    with pytest.raises(BridgeError, match="TOP_LEVEL"):
        resources(copy.deepcopy(record), "image", {}, "v1")
    record["manifest"]["files"] = []
    with pytest.raises(BridgeError, match="NO_INDEPENDENT_TESTS"):
        resources(record, "image", {}, "v1")


def test_question_sidecar_is_atomic_and_transferred_as_qa(setup):
    engine, backend, store = setup
    task, result = receipt(engine, backend)
    data = b'{"question":"Which boundary should be accepted?"}'
    result["snapshot"]["manifest"]["files"].append({"path": "bridge_question.json", "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(), "content_base64": base64.b64encode(data).decode()})
    digest = hashlib.sha256(canonical(result["snapshot"]["manifest"]).encode()).hexdigest()
    result["snapshot"]["digest"] = result["tests"]["manifest_digest"] = digest
    import_result(engine, task["id"], result)
    import_result(engine, task["id"], result)
    messages = engine.inspect(task["id"])["messages"]
    assert len(messages) == 1
    q = messages[0]
    assert q["sender"] == backend.profile and q["recipient"] == "owner"
    answer = engine.message("answer", task["id"], backend.profile, "Include equality.", q["id"])
    child = engine.continuation("child", task["id"], q["id"], answer["id"])
    with store.connect() as c:
        spec = json.loads(c.execute("SELECT spec FROM tasks WHERE id=?", (child["id"],)).fetchone()[0])
    assert "bridge_question.json" not in spec["inputs"]
    assert "Include equality." in spec["description"]
    assert spec["inputs"]["main.py"].startswith("print")


def test_question_only_batch_does_not_execute_partial_code():
    record = {"digest": "a"*64, "manifest": {"files": [{"path": "bridge_question.json",
        "content_base64": base64.b64encode(b'{"question":"Clarify?"}').decode()}]}}
    _, cm, _ = resources(record, "image", {}, "v1")
    assert "unittest" not in cm["data"]["verify_runner.py"]
    assert "json.loads" in cm["data"]["verify_runner.py"]


def test_seccomp_derivation_keeps_default_deny_and_blocks_network_and_uring():
    import runpy
    from pathlib import Path
    builder = runpy.run_path(str(Path(__file__).resolve().parents[1]/"scripts/build_seccomp.py"))
    source = {"defaultAction": "SCMP_ACT_ERRNO", "syscalls": [
        {"names": ["read", "write", "socket", "connect", "io_uring_setup"], "action": "SCMP_ACT_ALLOW"}]}
    original = copy.deepcopy(source)
    result = builder["derive"](source)
    assert source == original
    allowed = {name for rule in result["syscalls"] if rule["action"] == "SCMP_ACT_ALLOW" for name in rule["names"]}
    assert allowed == {"read", "write"}
    denied = {name for rule in result["syscalls"] if rule["action"] == "SCMP_ACT_ERRNO" for name in rule["names"]}
    assert {"socket", "connect", "socketpair", "socketcall", "io_uring_setup", "io_uring_enter"} <= denied
    with pytest.raises(ValueError):
        builder["derive"]({"defaultAction": "SCMP_ACT_ALLOW", "syscalls": source["syscalls"]})
