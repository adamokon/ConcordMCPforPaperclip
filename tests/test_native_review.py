"""Actual-shaped non-tool interaction contract; reassignment cancels a run."""

import copy
import errno
import json
import uuid
from pathlib import Path

import pytest

from concord_paperclip import codex_receipt as receipt
from concord_paperclip.native_review import KEY, binding, handoff
from concord_paperclip.policy import BridgeError
from test_codex_receipt import native_setup as _native_setup, repair_run


@pytest.fixture
def native_setup(tmp_path, monkeypatch):
    return _native_setup.__wrapped__(tmp_path, monkeypatch)


def test_reassignment_reproduces_installed_cancellation(native_setup):
    config, ctx, backend, _ = native_setup
    backend.rows[0]["status"] = "running"
    backend.patch(ctx["issue_id"], {"status": "in_review", "assigneeAgentId": None})
    assert backend.rows[0]["status"] == "cancelled"
    assert receipt.receive(config, ctx, backend)["failure"] == "cancelled"


def test_review_retains_run_and_assignment_with_no_wake(native_setup):
    config, ctx, backend, _ = native_setup
    config["executor_agent_id"] = ctx["profile"]
    run = backend.rows[0]
    run["status"] = "running"
    backend.current["status"] = "in_progress"
    backend.current["checkoutRunId"] = run["id"]
    result = receipt.executor_handoff(config, backend, run["id"])
    assert result["interaction_id"] == backend.interactions[0]["id"]
    assert backend.rows[0]["status"] == "running"
    assert backend.current["assigneeAgentId"] == ctx["profile"]
    assert backend.interactions[0]["continuationPolicy"] == "none"
    assert "addresseeAgentId" not in backend.interactions[0]
    assert backend.writes == [{"status": "in_review"}]
    receipt.executor_handoff(config, backend, run["id"])
    assert backend.interaction_posts == 1 and len(backend.writes) == 1


def test_uncertain_create_reconciles_only_existing_card(native_setup):
    config, _, backend, _ = native_setup
    run = backend.rows[0]
    run["status"] = "running"
    backend.uncertain_card = True
    with pytest.raises(BridgeError, match="NETWORK_UNCERTAIN"):
        handoff(config, backend, run, backend.issue(None))
    handoff(config, backend, run, backend.issue(None))
    assert backend.interaction_posts == 1
    backend.interactions.clear()
    with pytest.raises(BridgeError, match="REQUIRES_RECONCILIATION"):
        handoff(config, backend, run, backend.issue(None))
    assert backend.interaction_posts == 1


def test_repair_handoff_survives_automatic_revalidation_not_history(native_setup):
    config, ctx, backend, _ = native_setup
    original = backend.rows[0]
    run = repair_run(config, ctx, backend)
    run["status"] = "running"
    backend.rows = [original, run]
    backend.current["status"] = "in_progress"
    handoff(config, backend, run, backend.issue(None))
    backend.action = None  # GET now returns {active:null}, no resolved history
    handoff(config, backend, run, backend.issue(None))
    run.update(status="succeeded", finishedAt=14)
    receipt.validate_repair(config, backend, run, original, backend.issue(None), active_only=False)
    receipt.receive(config, ctx, backend)
    assert backend.interaction_posts == 1
    # Immutable run telemetry alone without its exact preserved review is insufficient.
    backend.interactions[0]["sourceRunId"] = str(uuid.uuid4())
    with pytest.raises(BridgeError, match="INVALID_DISPOSITION_REPAIR"):
        receipt.receive(config, ctx, backend)


def status(uids="999 999 999 999", nnp="1", eff="0", prm="0", amb="0"):
    return f"Uid:\t{uids}\nNoNewPrivs:\t{nnp}\nCapEff:\t{eff}\nCapPrm:\t{prm}\nCapAmb:\t{amb}\n"


@pytest.mark.parametrize("kind", ["unrelated", "same_uid", "mixed", "marker", "vanished", "esrch",
                                   "nnp", "eff", "prm", "amb", "malformed", "unknown_uid"])
def test_kernel_uid_cleanup_domain(tmp_path, monkeypatch, kind):
    run = str(uuid.uuid4())
    proc = tmp_path / "123"
    proc.mkdir()
    values = dict(uids="994 994 994 994" if kind == "unrelated" else "999 999 999 999")
    if kind == "mixed":
        values["uids"] = "994 994 999 994"
    if kind == "nnp":
        values["nnp"] = "0"
    if kind in {"eff", "prm", "amb"}:
        values[kind] = "0000000000000001"
    (proc / "status").write_text(status(**values) if kind != "malformed" else "Uid: 999\n")
    if kind == "unknown_uid":
        (proc / "status").unlink()
    original_bytes = Path.read_bytes
    def read_bytes(path):
        if path == proc / "environ":
            if kind in {"unrelated", "same_uid", "mixed"}:
                raise PermissionError(errno.EACCES, "nondumpable")
            if kind in {"vanished", "esrch"}:
                raise OSError(errno.ENOENT if kind == "vanished" else errno.ESRCH, "exited")
            return b"PAPERCLIP_RUN_ID=" + run.encode() + b"\0" if kind == "marker" else b""
        return original_bytes(path)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    if kind in {"same_uid", "mixed", "nnp", "eff", "prm", "amb", "malformed"}:
        with pytest.raises(BridgeError, match="VISIBILITY"):
            receipt.processes_empty(run, tmp_path, executor_uid=999)
    else:
        assert receipt.processes_empty(run, tmp_path, executor_uid=999) is (kind != "marker")
    if kind == "unrelated":
        with pytest.raises(BridgeError, match="VISIBILITY"):
            receipt.processes_empty(run, tmp_path)  # default full scan is unchanged


@pytest.mark.parametrize("uid", [True, "999", -1, 0])
def test_invalid_uid_never_changes_domain(tmp_path, uid):
    with pytest.raises(BridgeError, match="INVALID_EXECUTOR_UID"):
        receipt.processes_empty(str(uuid.uuid4()), tmp_path, executor_uid=uid)


def test_both_receive_and_recovery_use_same_profile_scope(native_setup, monkeypatch):
    config, ctx, backend, _ = native_setup
    config["profiles"][ctx["profile"]]["executor_uid"] = 999
    calls = []
    def clean(run, *, executor_uid):
        calls.append((run, executor_uid))
        return True
    monkeypatch.setattr(receipt, "processes_empty", clean)
    receipt.receive(config, ctx, backend)
    from test_codex_receipt import recovery_action
    recovery_action(config, ctx, backend)
    receipt.resolve_recovery(config, ctx, backend)
    assert len(calls) >= 3 and all(uid == 999 for _, uid in calls)


@pytest.fixture
def reviewed(setup, monkeypatch):
    from test_synthetic_review import prepared
    from concord_paperclip.automation import import_result
    from concord_paperclip.synthetic_review import approve
    engine, backend, store, task, result, config = prepared(setup)
    result["native_review_required"] = True
    remote = backend.rows[task["issue_id"]]
    remote.update(projectId=str(uuid.uuid4()), description="Bridge reference: " + task["id"])
    manifest = result["snapshot"]["manifest"]
    run = dict(id=manifest["run_id"], companyId=backend.company_id, agentId=backend.profile,
               status="succeeded", contextSnapshot={"issueId": task["issue_id"]}, createdAt=10, finishedAt=12)
    from concord_paperclip.native_review import PROMPT
    data = binding(run, remote)
    card = dict(id=str(uuid.uuid4()), kind="request_confirmation", status="pending",
                companyId=backend.company_id, issueId=task["issue_id"], sourceRunId=run["id"],
                createdByAgentId=backend.profile, effectiveResolverPolicy="anyone", continuationPolicy="none",
                idempotencyKey="native-review:" + run["id"], createdAt=11,
                payload=dict(version=1, prompt=PROMPT, supersedeOnUserComment=False, detailsMarkdown=json.dumps(data),
                             target=dict(type="custom", key=KEY, revisionId=run["id"])))
    backend.segment = lambda value: value
    backend.interactions = [card]
    backend.accepts = 0
    backend.run = lambda identity: copy.deepcopy(run) if identity == run["id"] else None
    def request(method, path, body=None):
        if method == "GET":
            return copy.deepcopy(backend.interactions)
        raise BridgeError("HTTP_409", "This completion review is no longer current or assigned to this agent.")
    backend.request = request
    from concord_paperclip.operator_review import CONTRACT, digest
    config["native_completion"] = dict(contract=CONTRACT, command=["/fixed/operator-review"],
                                       policy_id="fixture-policy", user_id="fixture-owner")
    def hook(command, value):
        assert command == ["/fixed/operator-review"]
        assert value["audit_actor"] == "operator-policy"
        assert value["manifest_digest"] == digest(value["manifest"])
        assert value["interaction_id"] == card["id"]
        assert value["card"]["sourceRunId"] == run["id"]
        assert value["reviews"][0]["payload"]["digest"] == value["manifest_digest"]
        backend.accepts += 1
        if getattr(backend, "uncommitted_accept", False):
            raise BridgeError("NETWORK_UNCERTAIN")
        card.update(status="accepted", resolvedByUserId="fixture-owner",
                    resolvedByAgentId=None, resolvedByRunId=None)
        remote["status"] = "done"
        if getattr(backend, "drop_accept", False):
            raise BridgeError("NETWORK_UNCERTAIN")
        return dict(version=1, contract=CONTRACT, audit_actor="operator-policy", policy_id="fixture-policy",
                    user_id="fixture-owner", request_sha256=digest(value), interaction_id=card["id"], status="accepted")
    monkeypatch.setattr("concord_paperclip.fixed_command.call", hook)
    import_result(engine, task["id"], result, "test.json")
    approve(engine, config)
    return engine, backend, store, task, result, config, card, run


def test_operator_review_accepts_once_under_real_process_context(reviewed):
    from test_synthetic_review import finalize_native
    engine, backend, store, task, _, config, card, _ = reviewed
    with pytest.raises(BridgeError, match="NATIVE_CONTEXT_REQUIRED"):
        engine.close_reviews()
    assert backend.accepts == 0
    finalize_native(engine, backend, config)
    engine.close_reviews()
    assert backend.accepts == 1 and card["status"] == "accepted"
    assert backend.rows[task["issue_id"]]["status"] == "done"
    with store.connect() as c:
        assert c.execute("SELECT count(*) FROM claims").fetchone()[0] == 0


@pytest.mark.parametrize("change", ["human", "foreign", "stale", "tool", "secret", "wake", "addressed", "other_pending",
                                   "cancelled_source", "wrong_source", "wrong_executor"])
def test_invalid_cards_never_accepted_or_closed(reviewed, change):
    from test_synthetic_review import finalize_native
    engine, backend, _, task, _, config, card, run = reviewed
    if change == "human":
        card["effectiveResolverPolicy"] = "human_only"
    elif change == "foreign":
        card["issueId"] = str(uuid.uuid4())
    elif change == "stale":
        card["payload"]["target"]["revisionId"] = str(uuid.uuid4())
    elif change in {"tool", "secret"}:
        card["payload"]["toolAction" if change == "tool" else "secretProposal"] = {}
    elif change == "wake":
        card["continuationPolicy"] = "wake_assignee"
    elif change == "addressed":
        card["addresseeAgentId"] = backend.profile
    elif change == "other_pending":
        backend.interactions.append(dict(id=str(uuid.uuid4()), status="pending", payload={}))
    elif change == "cancelled_source":
        run["status"] = "cancelled"
    elif change == "wrong_source":
        card["sourceRunId"] = str(uuid.uuid4())
    elif change == "wrong_executor":
        card["createdByAgentId"] = str(uuid.uuid4())
    with pytest.raises(BridgeError):
        finalize_native(engine, backend, config)
    assert backend.accepts == 0 and backend.rows[task["issue_id"]]["status"] == "in_review"


def test_lost_accept_reply_reconciles_without_another_accept(reviewed):
    from test_synthetic_review import finalize_native
    engine, backend, _, task, _, config, _, _ = reviewed
    backend.drop_accept = True
    with pytest.raises(BridgeError, match="NETWORK_UNCERTAIN"):
        finalize_native(engine, backend, config)
    engine.close_reviews()
    assert backend.accepts == 1 and engine.inspect(task["id"])["state"] == "complete"


def test_uncommitted_accept_never_retried(reviewed):
    from test_synthetic_review import finalize_native
    engine, backend, _, task, _, config, _, _ = reviewed
    backend.uncommitted_accept = True
    with pytest.raises(BridgeError, match="NETWORK_UNCERTAIN"):
        finalize_native(engine, backend, config)
    with pytest.raises(BridgeError, match="REQUIRES_RECONCILIATION"):
        engine.close_reviews()
    assert backend.accepts == 1 and engine.inspect(task["id"])["state"] == "review_queued"


@pytest.mark.skipif(not Path("/proc/self/status").is_file(), reason="Linux procfs integration")
def test_live_process_marker_and_exit(tmp_path):
    import os
    import subprocess
    import sys
    run = str(uuid.uuid4())
    child = subprocess.Popen([sys.executable, "-c", "import sys,time;print('ready',flush=True);time.sleep(30)"],
                             env={"PAPERCLIP_RUN_ID": run}, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "ready"
        (tmp_path / str(child.pid)).symlink_to(Path("/proc") / str(child.pid), target_is_directory=True)
        assert not receipt.processes_empty(run, tmp_path)
        child.terminate()
        child.wait(timeout=5)
        assert receipt.processes_empty(run, tmp_path)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        child.stdout.close()
    assert os.getpid() != child.pid


def test_unreadable_status_cannot_establish_unrelated_uid(tmp_path, monkeypatch):
    proc = tmp_path / "123"
    proc.mkdir()
    def denied(_):
        raise PermissionError(errno.EACCES, "status inaccessible")
    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(BridgeError, match="VISIBILITY"):
        receipt.processes_empty(str(uuid.uuid4()), tmp_path, executor_uid=999)


@pytest.mark.parametrize("change", ["source", "owner", "cause", "task", "origin", "time"])
def test_historical_repair_requires_exact_preserved_authoritative_binding(native_setup, change):
    config, ctx, backend, _ = native_setup
    original = backend.rows[0]
    run = repair_run(config, ctx, backend)
    backend.rows = [original, run]
    handoff(config, backend, run, backend.issue(None))
    backend.action = None
    data = json.loads(backend.interactions[0]["payload"]["detailsMarkdown"])
    if change == "source":
        data["recovery_action"]["evidence"]["latestRunId"] = str(uuid.uuid4())
    elif change == "owner":
        data["recovery_action"]["ownerAgentId"] = str(uuid.uuid4())
    elif change == "cause":
        data["recovery_action"]["cause"] = "other"
    elif change == "task":
        data["task_id"] = str(uuid.uuid4())
    elif change == "origin":
        run["contextSnapshot"]["source"] = "human"
    elif change == "time":
        run["createdAt"] = 1
    backend.interactions[0]["payload"]["detailsMarkdown"] = json.dumps(data)
    with pytest.raises(BridgeError):
        receipt.validate_repair(config, backend, run, original, backend.issue(None), active_only=False)


def test_new_active_recovery_cannot_be_masked_by_old_review(native_setup):
    config, ctx, backend, _ = native_setup
    original = backend.rows[0]
    run = repair_run(config, ctx, backend)
    backend.rows = [original, run]
    handoff(config, backend, run, backend.issue(None))
    backend.action["id"] = str(uuid.uuid4())
    with pytest.raises(BridgeError, match="INVALID_DISPOSITION_REPAIR"):
        receipt.validate_repair(config, backend, run, original, backend.issue(None), active_only=False)


def test_http_agent409_and_explicit_operator_hook_with_real_run_audit(reviewed, tmp_path, monkeypatch):
    """Installed gate: a separate control Process cannot accept the reserved card.

    Only the preselected fixed operator capability resolves it as a board user.
    The loopback HTTP services here are fixtures, not live Paperclip/K3s evidence.
    """
    import sys
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from unittest.mock import patch

    from concord_paperclip import native, operator_review
    from concord_paperclip.paperclip import Paperclip

    engine, fake, _, task, result, config, card, source = reviewed
    run_id, control = str(uuid.uuid4()), str(uuid.uuid4())
    config.update(company_id=fake.company_id, project_id=fake.rows[task["issue_id"]]["projectId"])
    rows = {task["issue_id"]: fake.rows[task["issue_id"]],
            control: dict(id=control, companyId=fake.company_id, projectId=config["project_id"],
                          assigneeAgentId=fake.profile)}
    control_run = dict(id=run_id, companyId=fake.company_id, agentId=fake.profile, status="running",
                       nativeIssueId=control, contextSnapshot={"issueId": control})
    events = []
    accepted_path = "/api/issues/" + task["issue_id"] + "/interactions/" + card["id"] + "/accept"
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def respond(self, status, data):
            self.send_response(status)
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        def scoped(self):
            return (self.headers.get("X-Paperclip-Run-Id") == run_id and
                    self.headers.get("Authorization") == "Bearer fixture-scoped")
        def do_GET(self):
            if "/heartbeat-runs/" in self.path and self.headers.get("Authorization") != "Bearer fixture-runtime":
                return self.respond(403, {})
            if self.path.endswith("/heartbeat-runs/" + run_id):
                data = control_run
            elif self.path.endswith("/heartbeat-runs/" + source["id"]):
                data = source
            elif self.path.endswith("/agents"):
                data = fake.agents()
            elif self.path.endswith("/interactions"):
                data = [card]
            else:
                data = rows[self.path.rsplit("/", 1)[-1]]
            self.respond(200, data)
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/fixed-operator-hook":
                # This fixture holds the owner authority. The caller gets only
                # this exact action, never a board token or arbitrary API path.
                if body != self.server.trusted_request:
                    return self.respond(403, {})
                events.append("operator_policy")
                board = Paperclip(self.server.url, fake.company_id, "fixture-board")
                board.request("POST", accepted_path, {})
                return self.respond(200, dict(
                    version=1, contract=operator_review.CONTRACT, audit_actor="operator-policy",
                    policy_id="fixture-policy", user_id="fixture-owner", status="accepted",
                    request_sha256=operator_review.digest(body), interaction_id=card["id"]))
            if self.path != accepted_path or body != {}:
                return self.respond(403, {})
            if self.headers.get("Authorization") != "Bearer fixture-board":
                if not self.scoped():
                    return self.respond(403, {})
                # No actual applied status_decision, reviewer addressee, decision
                # revision, or matching native issue/run context and lock exists.
                # This reproduces assertRequestConfirmationResolutionAllowedUnderLock.
                assert control_run["nativeIssueId"] != task["issue_id"]
                assert not card.get("addresseeAgentId")
                assert card["payload"]["target"]["revisionId"] == source["id"]
                assert "nativeReviewDecisionId" not in control_run["contextSnapshot"]
                events.append("agent409")
                return self.respond(409, {"error": "This completion review is no longer current or assigned to this agent."})
            assert self.headers.get("X-Paperclip-Run-Id") is None
            events.append("board_accept")
            card.update(status="accepted", resolvedByUserId="fixture-owner",
                        resolvedByAgentId=None, resolvedByRunId=None)
            rows[task["issue_id"]]["status"] = "done"
            self.respond(200, card)
        def do_PATCH(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if not self.scoped() or not self.path.endswith("/" + control):
                return self.respond(403, {})
            assert body == {"status": "done"}
            events.append("control_done")
            rows[control].update(body)
            self.respond(200, rows[control])
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.url = "http://127.0.0.1:" + str(server.server_port)
    # Construct independently from the trusted fixture's stored receipt and
    # review records, not by reflecting the hook's incoming request.
    with engine.store.connect() as c:
        approval = dict(c.execute("SELECT owner,key,payload FROM operations WHERE kind='review'").fetchone())
        approval["payload"] = json.loads(approval["payload"])
        submission = dict(c.execute("SELECT owner,key FROM operations WHERE kind='submit'").fetchone())
    submission["spec_digest"] = config["synthetic_review"]["tasks"][0]["spec_digest"]
    pending = {k: card.get(k) for k in (
        "id", "companyId", "issueId", "kind", "createdAt", "createdByAgentId", "sourceRunId",
        "idempotencyKey", "continuationPolicy", "effectiveResolverPolicy", "payload")}
    server.trusted_request = dict(
        version=1, contract=operator_review.CONTRACT, action="accept_exact_completion_review",
        audit_actor="operator-policy", policy_id="fixture-policy", user_id="fixture-owner",
        task_id=task["id"], issue_id=task["issue_id"], interaction_id=card["id"], card=pending,
        manifest=result["snapshot"]["manifest"], manifest_digest=result["snapshot"]["digest"],
        submission=submission, independent_tests=[result["tests"]], reviews=[approval])
    helper = tmp_path / "hook.py"
    helper.write_text("import sys,urllib.request\n"
                      "data=sys.stdin.buffer.read()\n"
                      "req=urllib.request.Request(sys.argv[1],data,{'Content-Type':'application/json'})\n"
                      "with urllib.request.urlopen(req) as r: sys.stdout.buffer.write(r.read())\n")
    config["native_completion"]["command"] = [sys.executable, "-I", str(helper), server.url + "/fixed-operator-hook"]
    # Restore the actual bounded subprocess exchange, overridden by reviewed.
    import importlib
    import concord_paperclip.fixed_command as fixed
    monkeypatch.setattr(fixed, "call", importlib.reload(fixed).call)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config["base_url"] = server.url
    api = Paperclip(server.url, fake.company_id, "fixture-scoped")
    engine.backend = api
    try:
        # A caller cannot select another issue/card/digest through the capability.
        changed = copy.deepcopy(server.trusted_request)
        changed["interaction_id"] = str(uuid.uuid4())
        with pytest.raises(BridgeError, match="HTTP_403"):
            api.request("POST", "/fixed-operator-hook", changed)
        with pytest.raises(BridgeError, match="HTTP_403"):
            api.request("POST", accepted_path, {})
        api.run_id = run_id
        with pytest.raises(BridgeError, match="HTTP_409"):
            api.request("POST", accepted_path, {})
        assert rows[task["issue_id"]]["status"] == "in_review" and card["status"] == "pending"
        with pytest.raises(BridgeError, match="NATIVE_CONTEXT_REQUIRED"):
            engine.close_reviews()  # receiver/timer lacks authenticated Process
        with patch.object(native, "make_engine", return_value=engine):
            native.execute(config, run_id, "fixture-runtime")
        assert events == ["agent409", "operator_policy", "board_accept", "control_done"]
        assert engine.inspect(task["id"])["state"] == "complete"
        assert card["resolvedByUserId"] == "fixture-owner" and card["resolvedByRunId"] is None
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.mark.parametrize("change", ["missing", "contract", "command", "user", "extra"])
def test_hook_must_be_selected_upfront_no_agent_fallback(reviewed, change):
    from test_synthetic_review import finalize_native
    engine, backend, _, _, _, config, _, _ = reviewed
    if change == "missing":
        del config["native_completion"]
    elif change == "contract":
        config["native_completion"]["contract"] = "agent-then-board"
    elif change == "command":
        config["native_completion"]["command"] = "sh -c anything"
    elif change == "user":
        config["native_completion"]["user_id"] = ""
    else:
        config["native_completion"]["fallback"] = True
    with pytest.raises(BridgeError, match="OPERATOR_REVIEW_CAPABILITY_REQUIRED"):
        finalize_native(engine, backend, config)
    assert backend.accepts == 0


@pytest.mark.parametrize("change", ["agent", "run", "user", "pending", "no_done", "receipt"])
def test_hook_cannot_fabricate_process_success(reviewed, monkeypatch, change):
    from test_synthetic_review import finalize_native
    from concord_paperclip import fixed_command
    engine, backend, _, task, _, config, card, _ = reviewed
    original = fixed_command.call
    def changed(command, value):
        result = original(command, value)
        if change == "agent":
            card["resolvedByAgentId"] = backend.profile
        elif change == "run":
            card["resolvedByRunId"] = str(uuid.uuid4())
        elif change == "user":
            card["resolvedByUserId"] = "other"
        elif change == "pending":
            card["status"] = "pending"
        elif change == "no_done":
            backend.rows[task["issue_id"]]["status"] = "in_review"
        else:
            result["request_sha256"] = "0" * 64
        return result
    monkeypatch.setattr(fixed_command, "call", changed)
    with pytest.raises(BridgeError):
        finalize_native(engine, backend, config)
    assert engine.inspect(task["id"])["state"] == "review_queued"


def test_legacy_rejected_intent_is_not_silently_superseded(reviewed):
    from test_synthetic_review import finalize_native
    engine, backend, store, task, result, config, card, _ = reviewed
    with store.transaction() as c:
        store.audit(c, "old-process", task["id"], "native_accept_intent",
                    {"interaction_id": card["id"], "digest": result["snapshot"]["digest"]})
    with pytest.raises(BridgeError, match="ACCEPT_WRITE_REQUIRES_RECONCILIATION"):
        finalize_native(engine, backend, config)
    assert backend.accepts == 0 and card["status"] == "pending"


def test_pass_without_explicit_review_does_not_invoke_hook(reviewed):
    from test_synthetic_review import finalize_native
    engine, backend, store, task, _, config, _, _ = reviewed
    with store.transaction() as c:
        c.execute("DELETE FROM operations WHERE kind='review'")
    with pytest.raises(BridgeError, match="VERIFIED_REVIEW_REQUIRED"):
        finalize_native(engine, backend, config)
    assert backend.accepts == 0


@pytest.mark.parametrize("field,value", [("status", "failed"), ("network_policy", "allow-all"),
                                         ("credential_free", False), ("seccomp", "foreign.json")])
def test_changed_independent_tests_cannot_call_hook(reviewed, field, value):
    from test_synthetic_review import finalize_native
    engine, backend, store, task, _, config, _, _ = reviewed
    with store.transaction() as c:
        row = c.execute("SELECT id,details FROM audit WHERE event='independent_tests'").fetchone()
        details = json.loads(row["details"])
        details[field] = value
        c.execute("UPDATE audit SET details=? WHERE id=?", (json.dumps(details), row["id"]))
    with pytest.raises(BridgeError, match="VERIFIED_REVIEW_REQUIRED"):
        finalize_native(engine, backend, config)
    assert backend.accepts == 0


@pytest.mark.parametrize("entrypoint", ["broker", "native"])
def test_operator_capability_requires_root_config_before_entrypoint(monkeypatch, entrypoint):
    from concord_paperclip.cli import main
    config = {"native_completion": {"contract": "operator-policy-native-accept-v1"}}
    monkeypatch.setattr("sys.argv", ["paperclip-bridge", "--config", "/untrusted.json", entrypoint])
    monkeypatch.setattr("concord_paperclip.cli.load_config", lambda _: config)
    calls = []
    def reject(path):
        calls.append(path)
        raise BridgeError("ROOT_OWNED_CONFIG_REQUIRED")
    monkeypatch.setattr("concord_paperclip.config.require_root_config", reject)
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1 and calls == ["/untrusted.json"]
