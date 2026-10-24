import base64
import copy
import hashlib
import json
import uuid

import pytest

from concord_paperclip.automation import import_result
from concord_paperclip.policy import BridgeError
from concord_paperclip.store import canonical
from concord_paperclip.synthetic_review import approve


def prepared(setup):
    engine, backend, store = setup
    data = {"main.py": b"def value(): return 1\n", "test_main.py": b"import unittest\nimport main\n"}
    spec = dict(title="Synthetic", description="Pure stdlib unit test", repo="demo",
                paths=["main.py", "test_main.py"], profile=None, parent_id=None, inputs={})
    rule = dict(submission_key="synthetic", spec_digest=hashlib.sha256(canonical(spec).encode()).hexdigest(),
                repo="demo", policy_id="public-stdlib-v1",
                sha256={path: hashlib.sha256(content).hexdigest() for path, content in data.items()})
    config = dict(native_agent_id=backend.profile, verifier_seccomp_profile="test.json",
                  synthetic_review=dict(enabled=True, tasks=[rule]))
    # Policy is installed before the first submit. No future task/run/digest is present.
    assert approve(engine, config) == []
    backend.wakes = []
    def wake_coordinator(agent, marker):
        backend.wakes.append((agent, marker))
        return {"id": str(uuid.uuid4())}
    backend.wake_coordinator = wake_coordinator
    task = engine.submit("synthetic", "Synthetic", "Pure stdlib unit test", "demo", ["main.py", "test_main.py"])
    engine.drain()
    task = engine.inspect(task["id"])
    task = engine.dispatch(task["id"], task["version"])
    run_id = str(uuid.uuid4())
    data = {"main.py": b"def value(): return 1\n", "test_main.py": b"import unittest\nimport main\n"}
    files = [{"path": path, "size": len(content), "sha256": hashlib.sha256(content).hexdigest(),
              "content_base64": base64.b64encode(content).decode()} for path, content in data.items()]
    manifest = dict(schema_version=1, task_id=task["id"], issue_id=task["issue_id"],
                    agent_id=backend.profile, run_id=run_id, files=files)
    digest = hashlib.sha256(canonical(manifest).encode()).hexdigest()
    result = {"snapshot": {"digest": digest, "manifest": manifest},
              "evidence": dict(issue_id=task["issue_id"], run_id=run_id, agent_id=backend.profile,
                               status="succeeded", environment_removed=True),
              "tests": dict(status="passed", manifest_digest=digest, credential_free=True,
                            network_policy="deny-all", seccomp="test.json", kind="unittest")}
    backend.rows[task["issue_id"]]["status"] = "in_review"
    return engine, backend, store, task, result, config


def test_default_disabled_and_opt_in_end_to_end_claims_slots_zero(setup):
    engine, backend, store, task, result, config = prepared(setup)
    import_result(engine, task["id"], result, "test.json")
    assert approve(engine, {}) == []
    assert engine.inspect(task["id"])["state"] == "review_ready"
    assert approve(engine, config)[0]["digest"] == result["snapshot"]["digest"]
    patches = backend.patches
    approve(engine, config)
    assert backend.patches == patches
    assert len(backend.wakes) == 1
    assert backend.rows[task["issue_id"]]["status"] == "in_review"
    finalize_native(engine, backend, config)
    assert approve(engine, config) == []
    assert backend.rows[task["issue_id"]]["status"] == "done"
    with store.connect() as c:
        assert c.execute("SELECT count(*) FROM claims").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM attempts WHERE state IN ('dispatching','running','uncertain')").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM audit WHERE event='machine_approval'").fetchone()[0] == 1


@pytest.mark.parametrize("kind", ["wrong_repo", "wrong_hash", "wrong_manifest", "wrong_paths", "not_handed_off"])
def test_policy_cannot_approve_arbitrary_pass(setup, kind):
    engine, backend, _, task, result, config = prepared(setup)
    import_result(engine, task["id"], result, "test.json")
    rule = config["synthetic_review"]["tasks"][0]
    if kind == "wrong_repo":
        rule["repo"] = "foreign"
    if kind == "wrong_hash":
        rule["sha256"]["main.py"] = "0" * 64
    if kind == "wrong_manifest":
        rule["manifest_digest"] = "0" * 64
    if kind == "wrong_paths":
        del rule["sha256"]["main.py"]
    if kind == "not_handed_off":
        backend.rows[task["issue_id"]]["status"] = "in_progress"
    with pytest.raises(BridgeError):
        approve(engine, config)
    assert engine.inspect(task["id"])["state"] == "review_ready"


def test_failed_tests_never_approve(setup):
    engine, backend, store, task, result, config = prepared(setup)
    result["tests"]["status"] = "failed"
    assert import_result(engine, task["id"], result, "test.json")["state"] == "verification_failed"
    assert approve(engine, config) == []
    with store.connect() as c:
        assert c.execute("SELECT count(*) FROM claims").fetchone()[0] == 2
        assert c.execute("SELECT count(*) FROM audit WHERE event='machine_approval'").fetchone()[0] == 0


def test_duplicate_import_rejects_different_manifest(setup):
    engine, _, _, task, result, _ = prepared(setup)
    import_result(engine, task["id"], result, "test.json")
    changed = copy.deepcopy(result)
    changed["snapshot"]["manifest"]["run_id"] = str(uuid.uuid4())
    with pytest.raises(BridgeError, match="RECEIPT_CONFLICT"):
        import_result(engine, task["id"], changed, "test.json")


def test_uncertain_done_write_reconciles_without_repeated_write(setup):
    engine, backend, store, task, result, config = prepared(setup)
    import_result(engine, task["id"], result, "test.json")
    approve(engine, config)
    backend.drop_patch_reply = True
    with pytest.raises(BridgeError, match="NETWORK_UNCERTAIN"):
        finalize_native(engine, backend, config)
    patches = backend.patches
    engine.close_reviews()
    assert backend.patches == patches
    assert engine.inspect(task["id"])["state"] == "complete"


def test_noncommitted_close_intent_requires_operator_reconciliation(setup):
    engine, backend, store, task, result, config = prepared(setup)
    import_result(engine, task["id"], result, "test.json")
    def denied(*_):
        raise BridgeError("HTTP_403")
    backend.patch = denied
    approve(engine, config)
    with pytest.raises(BridgeError, match="HTTP_403"):
        finalize_native(engine, backend, config)
    with pytest.raises(BridgeError, match="REQUIRES_RECONCILIATION"):
        engine.close_reviews()
    assert engine.inspect(task["id"])["state"] == "review_queued"
    with store.connect() as c:
        assert c.execute("SELECT count(*) FROM claims").fetchone()[0] == 2


def test_machine_approval_record_is_bound_to_tested_digest(setup):
    engine, _, store, task, result, config = prepared(setup)
    import_result(engine, task["id"], result, "test.json")
    approve(engine, config)
    with store.connect() as c:
        event = json.loads(c.execute("SELECT details FROM audit WHERE event='machine_approval'").fetchone()[0])
    assert event["digest"] == result["tests"]["manifest_digest"]
    assert event["policy_id"] == "public-stdlib-v1"


@pytest.mark.parametrize("passed", [True, False])
def test_real_isolated_python_runner_reports_assertion_outcome(tmp_path, passed):
    import subprocess
    import sys
    from concord_paperclip.sandbox import resources
    test = ("import unittest\nclass PublicTest(unittest.TestCase):\n"
            f"    def test_value(self): self.assertEqual(1, {1 if passed else 2})\n")
    record = {"digest": "a" * 64, "manifest": {"files": [{"path": "test_public.py",
              "content_base64": base64.b64encode(test.encode()).decode()}]}}
    _, cm, _ = resources(record, "public-test-image", {}, "fixture")
    for path, data in cm["data"].items():
        (tmp_path / path).write_text(data.replace("/workspace", str(tmp_path)))
    result = subprocess.run([sys.executable, "-I", "-S", "-B", str(tmp_path / "verify_runner.py")],
                            capture_output=True, timeout=10, env={})
    assert result.returncode == (0 if passed else 1)
    # This proves real unittest outcome only; K3s isolation remains an operator E2E check.


def test_late_observation_cannot_reset_review_ready(setup):
    engine, _, _, task, result, _ = prepared(setup)
    import_result(engine, task["id"], result, "test.json")
    version = engine.inspect(task["id"])["version"]
    engine.observe(task["id"], result["evidence"])
    assert engine.inspect(task["id"])["state"] == "review_ready"
    assert engine.inspect(task["id"])["version"] == version


def finalize_native(engine, backend, config):
    from unittest.mock import patch
    from concord_paperclip.native import execute
    run_id = str(uuid.uuid4())
    control = str(uuid.uuid4())
    backend.rows[control] = {"id": control, "assigneeAgentId": backend.profile}
    config = {**config, "base_url": "https://example.invalid", "company_id": backend.company_id}
    class Runtime:
        def __init__(self, *args, **kwargs):
            assert args[2] == "fixture-runtime-token" and kwargs["run_id"] == run_id
        def run(self, identity):
            if identity != run_id:
                return backend.run(identity)
            return dict(id=run_id, companyId=backend.company_id, agentId=backend.profile,
                        status="running", contextSnapshot={"issueId": control})
        def agents(self):
            return backend.agents()
    original = backend.patch
    def authenticated_patch(identity, data):
        assert backend.run_id == run_id
        return original(identity, data)
    with patch("concord_paperclip.native.make_engine", return_value=engine), \
            patch("concord_paperclip.native.Paperclip", Runtime), \
            patch.object(backend, "patch", side_effect=authenticated_patch):
        return execute(config, run_id, "fixture-runtime-token")


def test_timer_requires_no_run_but_native_completion_does(setup, monkeypatch):
    from concord_paperclip.native import execute
    engine, backend, _, task, result, config = prepared(setup)
    monkeypatch.delenv("PAPERCLIP_RUN_ID", raising=False)
    monkeypatch.delenv("PAPERCLIP_API_KEY", raising=False)
    import_result(engine, task["id"], result, "test.json")
    before = backend.patches
    approve(engine, config)
    assert backend.patches == before
    with pytest.raises(BridgeError, match="NATIVE_CONTEXT_REQUIRED"):
        execute(config)
    assert engine.inspect(task["id"])["state"] == "review_queued"
    finalize_native(engine, backend, config)
    assert engine.inspect(task["id"])["state"] == "complete"


@pytest.mark.parametrize("field", ["submission_key", "spec_digest"])
def test_preauthorized_rule_rejects_different_submission(setup, field):
    engine, _, _, task, result, config = prepared(setup)
    import_result(engine, task["id"], result, "test.json")
    config["synthetic_review"]["tasks"][0][field] = "foreign"
    if field == "spec_digest":
        with pytest.raises(BridgeError, match="SYNTHETIC_SPEC_MISMATCH"):
            approve(engine, config)
    else:
        assert approve(engine, config) == []
    assert engine.inspect(task["id"])["state"] == "review_ready"


def test_crash_between_review_and_wake_and_uncertain_create_never_replays(setup):
    engine, backend, _, task, result, config = prepared(setup)
    import_result(engine, task["id"], result, "test.json")
    from unittest.mock import patch
    with patch("concord_paperclip.wake.wake", side_effect=RuntimeError("crash")):
        with pytest.raises(RuntimeError):
            approve(engine, config)
    def uncertain(*args):
        backend.wakes.append(args)
        raise BridgeError("NETWORK_UNCERTAIN")
    backend.wake_coordinator = uncertain
    assert approve(engine, config)[0]["executor"]["state"] == "uncertain"
    approve(engine, config)
    assert len(backend.wakes) == 1
    assert engine.inspect(task["id"])["state"] == "review_queued"


def test_model_coordinator_configuration_never_wakes(setup):
    engine, backend, _, task, result, config = prepared(setup)
    import_result(engine, task["id"], result, "test.json")
    backend.agents = lambda: [{"id": backend.profile, "adapterType": "codex_local"}]
    with pytest.raises(BridgeError, match="NON_MODEL_COORDINATOR_REQUIRED"):
        approve(engine, config)
    assert backend.wakes == []
