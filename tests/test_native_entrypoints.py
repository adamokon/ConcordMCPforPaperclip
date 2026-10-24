import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from concord_paperclip.codex_receipt import native_verify
from concord_paperclip.executor_wrapper import execute
from concord_paperclip.fixed_command import call
from concord_paperclip.policy import BridgeError
from test_codex_receipt import native_setup as _native_setup


@pytest.fixture
def native_setup(tmp_path, monkeypatch):
    return _native_setup.__wrapped__(tmp_path, monkeypatch)


def test_fixed_command_json_roundtrip_and_bounds():
    assert call([sys.executable, "-c", "import sys;sys.stdout.write(sys.stdin.read())"],
                {"snapshot": "public"}, limit=1024) == {"snapshot": "public"}
    for command, code in [([sys.executable, "-c", "print('x'*4096)"], "OUTPUT_LIMIT"),
                          ([sys.executable, "-c", "import time;time.sleep(10)"], "TIMEOUT"),
                          ([sys.executable, "-c", "print('invalid json')"], "FAILED"),
                          ([sys.executable, "-c", "raise SystemExit(1)"], "FAILED")]:
        with pytest.raises(BridgeError, match=code):
            call(command, {}, timeout=0.3, limit=1024)
    with pytest.raises(BridgeError, match="INPUT_LIMIT"):
        call([sys.executable], {"large": "x" * 2048}, limit=1024)
    with pytest.raises(BridgeError, match="INVALID_FIXED_COMMAND"):
        call("shell command", {})


@pytest.mark.parametrize("field,value", [("manifest_digest", "foreign"), ("status", "unknown"),
                                         ("seccomp", "unconfined"), ("credential_free", False),
                                         ("network_policy", "allow-all")])
def test_remote_verifier_fail_closed(native_setup, monkeypatch, field, value):
    from concord_paperclip.codex_receipt import receive
    config, context, backend, _ = native_setup
    record = receive(config, context, backend)["snapshot"]
    config["native_verify_command"] = ["/fixed/remote-verifier"]
    tests = dict(manifest_digest=record["digest"], status="passed", credential_free=True,
                 network_policy="deny-all", seccomp="test.json")
    tests[field] = value
    monkeypatch.setattr("concord_paperclip.fixed_command.call", lambda *a, **k: tests)
    with pytest.raises(BridgeError, match="INVALID_VERIFIER_RECEIPT"):
        native_verify(config, record)


def test_remote_verifier_receives_exact_snapshot_and_preserves_failed(native_setup, monkeypatch):
    from concord_paperclip.codex_receipt import receive
    config, context, backend, _ = native_setup
    record = receive(config, context, backend)["snapshot"]
    config["native_verify_command"] = ["/fixed/forced-ssh"]
    def verify(command, request, **kwargs):
        assert command == ["/fixed/forced-ssh"] and request == record
        assert kwargs == {"timeout": 100, "limit": 2_000_000}
        return dict(manifest_digest=request["digest"], status="failed", credential_free=True,
                    network_policy="deny-all", seccomp="test.json")
    monkeypatch.setattr("concord_paperclip.fixed_command.call", verify)
    monkeypatch.setattr("concord_paperclip.gateway.verify", lambda *_: pytest.fail("local verifier called"))
    assert native_verify(config, record)["status"] == "failed"


@pytest.mark.parametrize("error", [False, True])
def test_operator_lease_revoked_in_finally_without_crossing_gateway(error, monkeypatch):
    from concord_paperclip.gateway import native_call
    backend = SimpleNamespace(token="fixture-ephemeral-token")
    config = {"native_token_revoke_command": ["/fixed/revoke"]}
    monkeypatch.setattr("concord_paperclip.gateway.native_backend", lambda _: backend)
    revoke = Mock(return_value={"revoked": True})
    monkeypatch.setattr("concord_paperclip.fixed_command.call", revoke)
    def operation(api):
        assert api is backend
        if error:
            raise BridgeError("HTTP_403")
        return {"status": "public-only"}
    if error:
        with pytest.raises(BridgeError, match="HTTP_403"):
            native_call(config, operation)
    else:
        assert native_call(config, operation) == {"status": "public-only"}
    revoke.assert_called_once_with(["/fixed/revoke"], {"token": "fixture-ephemeral-token"},
                                   timeout=10, limit=32768)
    assert backend.token == ""


@pytest.mark.parametrize("ordinary,exitcode", [(True, 0), (False, 0), (False, 2)])
def test_executor_wrapper_passthrough_and_own_handoff(native_setup, monkeypatch, ordinary, exitcode):
    config, context, backend, _ = native_setup
    config.update(native_cli_command=["/fixed/codex"], executor_agent_id=context["profile"],
                  reviewer_user_id="fixture-reviewer")
    run = backend.rows[0]
    run["status"] = "running"
    if ordinary:
        backend.current["description"] = "Ordinary task"
    monkeypatch.setenv("PAPERCLIP_RUN_ID", run["id"])
    monkeypatch.setenv("PAPERCLIP_API_KEY", "fixture-runtime-token")
    process = Mock(return_value=SimpleNamespace(returncode=exitcode))
    monkeypatch.setattr("concord_paperclip.executor_wrapper.subprocess.run", process)
    arguments = ["exec", "--json", "literal $(no-shell) argument"]
    assert execute(config, arguments, backend=backend) == exitcode
    process.assert_called_once_with(["/fixed/codex", *arguments], check=False)
    assert bool(backend.interactions) is (not ordinary and exitcode == 0)
    if backend.writes:
        assert backend.writes[0]["status"] == "in_review"


def test_wrapper_without_native_context_passthrough(monkeypatch):
    monkeypatch.delenv("PAPERCLIP_RUN_ID", raising=False)
    monkeypatch.delenv("PAPERCLIP_API_KEY", raising=False)
    assert execute({"native_cli_command": [sys.executable]}, ["-c", "raise SystemExit(0)"]) == 0


def test_receiver_example_can_be_installed_before_submit():
    from pathlib import Path
    config = json.loads(Path("examples/native-receiver.example.json").read_text())
    rule = config["synthetic_review"]["tasks"][0]
    assert "submission_key" in rule and "spec_digest" in rule
    assert "task_id" not in rule and "manifest_digest" not in rule


def test_remote_forced_command_validates_content_before_execution(native_setup):
    import copy
    from concord_paperclip.codex_receipt import receive
    from concord_paperclip.native_verifier import validate
    config, context, backend, _ = native_setup
    record = receive(config, context, backend)["snapshot"]
    assert validate(record) == record
    changed = copy.deepcopy(record)
    changed["manifest"]["files"][0]["content_base64"] = "Zm9yZWlnbg=="
    from concord_paperclip.store import canonical
    import hashlib
    changed["digest"] = hashlib.sha256(canonical(changed["manifest"]).encode()).hexdigest()
    with pytest.raises(BridgeError, match="UNSAFE_ARTIFACT"):
        validate(changed)


@pytest.mark.parametrize("hidden_runtime_roster", [False, True])
def test_legacy_agy_final_done_uses_scoped_key_and_real_run_header(setup, monkeypatch, hidden_runtime_roster):
    """Legacy AGY close via native Process, not reserved native-card acceptance."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from concord_paperclip import native
    from concord_paperclip.paperclip import Paperclip
    from unittest.mock import patch
    import uuid

    engine, backend, _, task, result, config = __import__("test_synthetic_review").prepared(setup)
    from concord_paperclip.automation import import_result
    from concord_paperclip.synthetic_review import approve
    import_result(engine, task["id"], result, "test.json")
    approve(engine, config)
    run_id, control = str(uuid.uuid4()), str(uuid.uuid4())
    rows = {task["issue_id"]: backend.rows[task["issue_id"]],
            control: {"id": control, "companyId": backend.company_id, "assigneeAgentId": backend.profile}}
    writes = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def respond(self, status, data):
            self.send_response(status)
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        def do_GET(self):
            if self.path.endswith("/heartbeat-runs/" + run_id):
                if self.headers.get("Authorization") != "Bearer fixture-runtime":
                    return self.respond(403, {})
                data = dict(id=run_id, companyId=backend.company_id, agentId=backend.profile,
                            status="running", contextSnapshot={"issueId": control})
            elif self.path.endswith("/agents"):
                data = ([] if hidden_runtime_roster or self.headers.get("Authorization") ==
                        "Bearer fixture-scoped" else backend.agents())
            else:
                data = rows[self.path.rsplit("/", 1)[-1]]
            self.respond(200, data)
        def do_PATCH(self):
            # Timer/no-native-context cannot satisfy this contract.
            if (self.headers.get("X-Paperclip-Run-Id") != run_id
                    or self.headers.get("Authorization") != "Bearer fixture-scoped"):
                return self.respond(403, {})
            value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            identity = self.path.rsplit("/", 1)[-1]
            writes.append((identity, value))
            rows[identity].update(value)
            self.respond(200, rows[identity])
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = "http://127.0.0.1:" + str(server.server_port)
    config.update(base_url=url, company_id=backend.company_id, project_id="fixture-project")
    import time
    proof = dict(id=config["native_agent_id"], company_id=config["company_id"],
                 project_id=config["project_id"], adapter_type="process", observed_at=time.time())
    monkeypatch.setattr("concord_paperclip.automation.gateway", lambda *_: {"_coordinator": proof})
    try:
        api = Paperclip(url, backend.company_id, "fixture-scoped")
        engine.backend = api
        assert api.agents() == []
        with pytest.raises(BridgeError, match="HTTP_403"):
            api.patch(task["issue_id"], {"status": "done"})
        assert not writes
        with patch.object(native, "make_engine", return_value=engine):
            with pytest.raises(BridgeError, match="HTTP_403"):
                native.execute(config, run_id, "fixture-invalid-runtime")
            assert not writes
            native.execute(config, run_id, "fixture-runtime")
        assert writes == [(task["issue_id"], {"status": "done"}), (control, {"status": "done"})]
        assert engine.inspect(task["id"])["state"] == "complete"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_unattended_receive_cycle_cli_policy_preinstalled_before_submit(setup, monkeypatch, capsys):
    from concord_paperclip.cli import main
    from test_synthetic_review import prepared, finalize_native
    engine, backend, store, task, result, config = prepared(setup)
    policy_before = json.dumps(config, sort_keys=True)
    monkeypatch.delenv("PAPERCLIP_RUN_ID", raising=False)
    monkeypatch.delenv("PAPERCLIP_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["paperclip-bridge", "--config", "/fixed/root.json", "receive-cycle"])
    monkeypatch.setattr("concord_paperclip.cli.load_config", lambda _: config)
    monkeypatch.setattr("concord_paperclip.config.require_root_config", lambda _: None)
    monkeypatch.setattr("concord_paperclip.cli.make_engine", lambda _: engine)
    monkeypatch.setattr("concord_paperclip.automation.gateway", lambda *_: result)
    before = backend.patches
    main()
    output = json.loads(capsys.readouterr().out)
    assert output["receipts"][0]["state"] == "review_ready"
    assert output["approvals"][0]["executor"]["state"] == "queued"
    assert backend.patches == before
    assert json.dumps(config, sort_keys=True) == policy_before
    finalize_native(engine, backend, config)
    assert engine.inspect(task["id"])["state"] == "complete"
    with store.connect() as connection:
        assert connection.execute("SELECT count(*) FROM claims").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM attempts WHERE state='running'").fetchone()[0] == 0


@pytest.mark.parametrize("change", [None, "source", "action", "owner", "cause", "origin", "foreign",
                                   "failed_source", "unknown", "wrong_time"])
def test_actual_repair_wake_never_invokes_provider(native_setup, monkeypatch, change):
    from test_codex_receipt import repair_run, uid
    config, ctx, backend, _ = native_setup
    config.update(native_cli_command=["/fixed/codex"], executor_agent_id=ctx["profile"],
                  reviewer_user_id="fixture-reviewer")
    repair = repair_run(config, ctx, backend)
    repair["status"] = "running"
    backend.rows = [*backend.rows, repair]
    backend.current["status"] = "in_progress"
    backend.current["executionRunId"] = repair["id"]
    backend.current["checkoutRunId"] = repair["id"]
    if change == "source":
        repair["contextSnapshot"]["dispositionRepairSourceRunId"] = repair["id"]
    elif change == "action":
        repair["contextSnapshot"]["recoveryActionId"] = uid()
    elif change == "owner":
        backend.action["ownerAgentId"] = uid()
    elif change == "cause":
        backend.action["cause"] = "other"
    elif change == "origin":
        repair["contextSnapshot"]["source"] = "human"
    elif change == "foreign":
        backend.current["projectId"] = uid()
    elif change == "failed_source":
        backend.rows[0]["status"] = "failed"
    elif change == "unknown":
        repair["contextSnapshot"]["wakeReason"] = "unknown_recovery"
    elif change == "wrong_time":
        repair["createdAt"] = 1
    monkeypatch.setenv("PAPERCLIP_RUN_ID", repair["id"])
    monkeypatch.setenv("PAPERCLIP_API_KEY", "fixture-runtime")
    monkeypatch.setattr("concord_paperclip.executor_wrapper.subprocess.run",
                        lambda *_a, **_k: pytest.fail("provider invoked for recovery"))
    if change:
        with pytest.raises(BridgeError):
            execute(config, [], backend=backend)
        assert not backend.writes
    else:
        assert execute(config, [], backend=backend) == 0
        assert execute(config, [], backend=backend) == 0
        assert len(backend.writes) == 1
        assert backend.writes[0]["status"] == "in_review"
        assert backend.current["assigneeAgentId"] == ctx["profile"]
        assert backend.interaction_posts == 1


def test_repair_without_authorized_context_never_invokes_provider(monkeypatch):
    monkeypatch.delenv("PAPERCLIP_RUN_ID", raising=False)
    monkeypatch.setenv("PAPERCLIP_WAKE_REASON", "issue_disposition_repair")
    monkeypatch.setattr("concord_paperclip.executor_wrapper.subprocess.run",
                        lambda *_a, **_k: pytest.fail("provider invoked"))
    with pytest.raises(BridgeError, match="INVALID_DISPOSITION_REPAIR"):
        execute({"native_cli_command": ["/fixed/codex"]}, [])


@pytest.mark.parametrize("field,value", [(None, None), ("observed_at", 0), ("observed_at", float("nan")),
    ("observed_at", float("inf")), ("observed_at", True), ("observed_at", "now"),
    ("observed_at", 10001), ("id", "foreign"), ("company_id", "foreign"),
    ("project_id", "foreign"), ("adapter_type", "codex_local"), ("missing", None)])
def test_hidden_scoped_roster_requires_fresh_pinned_gateway_proof(setup, monkeypatch, field, value):
    from test_synthetic_review import prepared
    from concord_paperclip.wake import wake
    engine, backend, _, task, _, config = prepared(setup)
    config.update(company_id=backend.company_id, project_id="fixture-project")
    backend.agents = lambda: []  # actual scoped-key live shape
    monkeypatch.setattr("concord_paperclip.wake.time.time", lambda: 10000)
    proof = dict(id=config["native_agent_id"], company_id=config["company_id"],
                 project_id=config["project_id"], adapter_type="process", observed_at=9999)
    if field:
        proof[field] = value
    monkeypatch.setattr("concord_paperclip.automation.gateway",
                        lambda *_: {} if field == "missing" else {"_coordinator": proof})
    if field:
        with pytest.raises(BridgeError, match="NON_MODEL_COORDINATOR_REQUIRED"):
            wake(engine, config, task["id"])
        assert not backend.wakes
    else:
        assert wake(engine, config, task["id"])["state"] == "queued"
        assert wake(engine, config, task["id"])["state"] == "done"
        assert len(backend.wakes) == 1


def test_gateway_emits_only_actual_pinned_process_metadata(native_setup, monkeypatch):
    from concord_paperclip.codex_receipt import probe
    from test_codex_receipt import uid
    config, ctx, backend, _ = native_setup
    coordinator = uid()
    config.update(native_probe_command=["/fixed/probe"], native_agent_id=coordinator)
    backend.active_runs = lambda: []
    backend.agents = lambda: [{"id": coordinator, "adapterType": "process"},
                             {"id": ctx["profile"], "adapterType": "codex_local", "status": "idle"}]
    monkeypatch.setattr("concord_paperclip.gateway.call", lambda *_: {"_coordinator": {"id": "forged"}})
    result = probe(config, backend)
    proof = result["_coordinator"]
    assert proof["id"] == coordinator and proof["adapter_type"] == "process"
    assert proof["company_id"] == config["company_id"] and proof["project_id"] == config["project_id"]
    assert set(proof) == {"id", "company_id", "project_id", "adapter_type", "observed_at"}
    backend.agents = lambda: []
    with pytest.raises(BridgeError, match="NON_MODEL_COORDINATOR_REQUIRED"):
        probe(config, backend)
