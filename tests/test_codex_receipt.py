import copy
import json
import uuid

import pytest

from concord_paperclip import codex_receipt as native
from concord_paperclip.policy import BridgeError
from concord_paperclip.readiness import evaluate


def uid():
    return str(uuid.uuid4())


@pytest.fixture
def native_setup(tmp_path, monkeypatch):
    company, project, agent, task, issue_id, attempt, run = [uid() for _ in range(7)]
    config = {"company_id": company, "project_id": project, "receipt_root": str(tmp_path / "receipts"),
              "test_seccomp_profile": "test.json", "handoff_root": str(tmp_path / "handoff"), "profiles": {agent: {"adapter_type": "codex_local",
              "artifact_base": str(tmp_path / "artifacts")}}}
    context = dict(task_id=task, issue_id=issue_id, profile=agent, company_id=company, project_id=project,
                   attempt_id=attempt, run_id=None, state="running", created=10, paths=["main.py", "test_main.py"])
    row = dict(id=run, companyId=company, agentId=agent, contextSnapshot={"issueId": issue_id},
               createdAt=11, finishedAt=12, status="succeeded")
    root = tmp_path / "artifacts" / run
    root.mkdir(parents=True)
    (root / "main.py").write_text("def value(): return 1\n")
    (root / "test_main.py").write_text("import unittest\n")

    class Backend:
        rows = [row]
        current = dict(id=issue_id, companyId=company, projectId=project, assigneeAgentId=agent,
                       description="Bridge reference: " + task, status="in_review")
        action = None
        writes = []
        error = None
        interactions = []
        interaction_posts = 0
        uncertain_card = False

        def issue(self, _):
            return copy.deepcopy(self.current)

        def run(self, identity):
            return copy.deepcopy(next(r for r in self.rows if r["id"] == identity))

        def company_path(self, resource):
            return "/api/companies/" + company + "/" + resource

        def segment(self, value):
            return value

        def request(self, method, path, data=None):
            if "/interactions" in path:
                if method == "GET":
                    return copy.deepcopy(self.interactions)
                self.interaction_posts += 1
                card = dict(data, id=uid(), companyId=company, issueId=issue_id,
                            sourceRunId=self.rows[-1]["id"], createdByAgentId=agent, status="pending",
                            effectiveResolverPolicy="anyone", createdAt=self.rows[-1]["createdAt"] + 0.1)
                self.interactions.append(card)
                if self.uncertain_card:
                    raise BridgeError("NETWORK_UNCERTAIN")
                return copy.deepcopy(card)
            if path.endswith("recovery-actions"):
                return {"active": copy.deepcopy(self.action)}
            if method == "POST":
                self.writes.append(data)
                if self.error:
                    raise BridgeError(self.error)
                self.current["status"] = data["sourceIssueStatus"]
                self.action = None
                return {}
            return copy.deepcopy(self.rows)

        def patch(self, identity, data):
            # Installed route cancels the active provider run on reassignment.
            if "assigneeAgentId" in data and data["assigneeAgentId"] != self.current["assigneeAgentId"]:
                self.rows[-1]["status"] = "cancelled"
            self.writes.append(data)
            self.current.update(data)

    def verify(config, record):
        return dict(manifest_digest=record["digest"], status="passed", seccomp="test.json",
                    credential_free=True, network_policy="deny-all", kind="unittest")

    monkeypatch.setattr("concord_paperclip.gateway.verify", verify)
    monkeypatch.setattr(native, "processes_empty", lambda run_id: True)
    return config, context, Backend(), root


def test_pins_first_run_and_immutable_snapshot_on_restart(native_setup):
    config, ctx, backend, root = native_setup
    result = native.receive(config, ctx, backend, clean=lambda _: True)
    later = repair_run(config, ctx, backend)
    backend.rows = [later, *backend.rows]
    (root / "main.py").write_text("changed after pinned snapshot")
    assert native.receive(config, ctx, backend, clean=lambda _: True) == result
    assert not backend.writes
    assert result["snapshot"]["manifest"]["run_id"] != later["id"]


@pytest.mark.parametrize("change,code", [
    (lambda c, x, b: x.update(run_id=uid()), "RUN_MISMATCH"),
    (lambda c, x, b: x.update(project_id=uid()), "CONTEXT_SCOPE_MISMATCH"),
    (lambda c, x, b: b.current.update(projectId=uid()), "ISSUE_SCOPE_MISMATCH"),
    (lambda c, x, b: b.rows[0].update(agentId=uid()), "RUN_MISMATCH"),
    (lambda c, x, b: b.rows[0].update(finishedAt=None), "INVALID_TERMINAL_EVIDENCE"),
    (lambda c, x, b: x.update(paths=["dir/"]), "AUTOMATIC_RECEIPT_REQUIRES_EXACT_PATHS"),
])
def test_scope_failures(native_setup, change, code):
    config, ctx, backend, _ = native_setup
    change(config, ctx, backend)
    with pytest.raises(BridgeError, match=code):
        native.receive(config, ctx, backend, clean=lambda _: True)


@pytest.mark.parametrize("kind", ["process", "lock", "running", "other_running"])
def test_pending_and_other_run_never_collect(native_setup, kind):
    config, ctx, backend, root = native_setup
    (root / "main.py").unlink()
    if kind == "lock":
        backend.current["checkoutRunId"] = backend.rows[0]["id"]
    if kind == "running":
        backend.rows[0]["status"] = "running"
    if kind == "other_running":
        backend.rows.append({**backend.rows[0], "id": uid(), "status": "running", "createdAt": 13})
        with pytest.raises(BridgeError, match="OTHER_RUN_ACTIVE"):
            native.receive(config, ctx, backend, clean=lambda _: True)
        return
    assert native.receive(config, ctx, backend, clean=lambda _: kind != "process") == {"pending": True}


@pytest.mark.parametrize("kind", ["missing", "symlink", "secret", "fifo"])
def test_bad_artifact_never_reaches_verifier(native_setup, kind, monkeypatch):
    import os
    config, ctx, backend, root = native_setup
    target = root / "main.py"
    target.unlink()
    if kind == "symlink":
        target.symlink_to(root / "test_main.py")
    if kind == "secret":
        target.write_text('"access_token":"synthetic-only-secret-value"')
    if kind == "fifo":
        os.mkfifo(target)
    monkeypatch.setattr("concord_paperclip.gateway.verify", lambda *_: pytest.fail("unsafe files verified"))
    with pytest.raises(BridgeError):
        native.receive(config, ctx, backend, clean=lambda _: True)


def test_truncated_telemetry_and_changed_pin_fail_closed(native_setup):
    config, ctx, backend, _ = native_setup
    original = backend.rows
    backend.rows = original * 1000
    with pytest.raises(BridgeError, match="INCOMPLETE"):
        native.receive(config, ctx, backend, clean=lambda _: True)
    backend.rows = original
    native.receive(config, ctx, backend, clean=lambda _: True)
    ctx["attempt_id"] = uid()
    with pytest.raises(BridgeError, match="BINDING_CHANGED"):
        native.receive(config, ctx, backend, clean=lambda _: True)


def test_failed_execution_requires_cleanup_and_skips_verifier(native_setup, monkeypatch):
    config, ctx, backend, _ = native_setup
    backend.rows[0]["status"] = "failed"
    monkeypatch.setattr("concord_paperclip.gateway.verify", lambda *_: pytest.fail("failed execution verified"))
    assert native.receive(config, ctx, backend, clean=lambda _: False) == {"pending": True}
    assert native.receive(config, ctx, backend, clean=lambda _: True)["failure"] == "failed"


def test_proc_marker_and_visibility(tmp_path, monkeypatch):
    run_id = uid()
    proc = tmp_path / "123"
    proc.mkdir()
    env = proc / "environ"
    env.write_bytes(b"OTHER=public\0PAPERCLIP_RUN_ID=" + run_id.encode() + b"\0")
    assert not native.processes_empty(run_id, tmp_path)
    env.write_bytes(b"OTHER=public\0")
    assert native.processes_empty(run_id, tmp_path)
    def denied(*_):
        raise PermissionError()
    monkeypatch.setattr(type(env), "read_bytes", denied)
    with pytest.raises(BridgeError, match="VISIBILITY"):
        native.processes_empty(run_id, tmp_path)


def test_native_readiness_without_agy_oauth():
    probe = dict(observed_at=100, agent_status="idle", adapter_type="codex_local", enrolled=True,
                 environment_empty=True, active_runs=0, credential_available=True,
                 provider_auth="unknown", provider_quota="unknown")
    assert evaluate(probe, 101)["eligible"]
    assert not evaluate(probe, 200)["eligible"]
    assert not evaluate({**probe, "credential_available": False}, 101)["eligible"]
    assert not evaluate({**probe, "active_runs": 1}, 101)["eligible"]


def recovery_action(config, ctx, backend):
    backend.action = dict(id=uid(), companyId=config["company_id"], sourceIssueId=ctx["issue_id"],
                          kind="deliberate_wait_without_target", cause="deliberate_wait_without_target",
                          ownerType="agent", ownerAgentId=ctx["profile"], status="active",
                          evidence={"latestRunId": backend.rows[0]["id"], "latestRunStatus": "succeeded"})


@pytest.mark.parametrize("key,value", [("ownerAgentId", "foreign"), ("kind", "export_failure"),
                                      ("sourceIssueId", "foreign"), ("status", "resolved"),
                                      ("evidence", {"latestRunId": "stale"})])
def test_recovery_rejects_foreign_stale_or_malformed(native_setup, key, value):
    config, ctx, backend, _ = native_setup
    native.receive(config, ctx, backend, clean=lambda _: True)
    recovery_action(config, ctx, backend)
    backend.action[key] = value
    with pytest.raises(BridgeError, match="RECOVERY_SCOPE"):
        native.resolve_recovery(config, ctx, backend)
    assert not backend.writes


@pytest.mark.parametrize("error", ["HTTP_403", "NETWORK_UNCERTAIN", None])
def test_recovery_uses_exact_contract_and_no_blind_retry(native_setup, error):
    config, ctx, backend, _ = native_setup
    native.receive(config, ctx, backend, clean=lambda _: True)
    recovery_action(config, ctx, backend)
    backend.error = error
    if error:
        with pytest.raises(BridgeError, match=error):
            native.resolve_recovery(config, ctx, backend)
        with pytest.raises(BridgeError, match="REQUIRES_RECONCILIATION"):
            native.resolve_recovery(config, ctx, backend)
    else:
        assert native.resolve_recovery(config, ctx, backend)["state"] == "resolved"
        assert native.resolve_recovery(config, ctx, backend)["state"] == "clear"
    assert len(backend.writes) == 1
    assert backend.writes[0]["sourceIssueStatus"] == "in_review"
    assert backend.writes[0]["outcome"] == "restored"


def test_executor_handoff_active_own_run_only(native_setup):
    config, ctx, backend, _ = native_setup
    config.update(executor_agent_id=ctx["profile"], reviewer_user_id="synthetic-reviewer")
    backend.rows[0]["status"] = "running"
    backend.current["executionRunId"] = backend.rows[0]["id"]
    assert native.executor_handoff(config, backend, backend.rows[0]["id"])["state"] == "in_review"
    assert backend.current["assigneeAgentId"] == ctx["profile"]
    assert backend.rows[0]["status"] == "running"
    assert backend.interaction_posts == 1
    assert native.executor_handoff(config, backend, backend.rows[0]["id"])["state"] == "in_review"
    assert len(backend.writes) == 0


def test_json_fixture_has_no_provider_data(native_setup):
    config, ctx, backend, _ = native_setup
    result = native.receive(config, ctx, backend, clean=lambda _: True)
    assert "token" not in json.dumps(result)


def test_fresh_exact_run_telemetry_is_required(native_setup):
    config, ctx, backend, _ = native_setup
    backend.run = lambda identity: {**backend.rows[0], "status": "running"}
    with pytest.raises(BridgeError, match="TELEMETRY_CHANGED"):
        native.receive(config, ctx, backend, clean=lambda _: True)


def test_pin_does_not_switch_when_original_disappears(native_setup):
    config, ctx, backend, _ = native_setup
    native.receive(config, ctx, backend, clean=lambda _: True)
    backend.rows = [{**backend.rows[0], "id": uid(), "createdAt": 13}]
    with pytest.raises(BridgeError, match="PINNED_RUN_UNAVAILABLE"):
        native.receive(config, ctx, backend, clean=lambda _: True)


def test_recovery_cannot_resolve_after_failed_verification(native_setup, monkeypatch):
    config, ctx, backend, _ = native_setup
    result = native.receive(config, ctx, backend, clean=lambda _: True)
    recovery_action(config, ctx, backend)
    monkeypatch.setattr("concord_paperclip.gateway.verify", lambda *_: {**result["tests"], "status": "failed"})
    with pytest.raises(BridgeError, match="VERIFIED_RECEIPT_REQUIRED"):
        native.resolve_recovery(config, ctx, backend)
    assert backend.writes == []


def test_gateway_native_route_uses_fixed_context(native_setup, monkeypatch):
    from concord_paperclip.gateway import execute
    config, ctx, backend, _ = native_setup
    config["context_command"] = ["/fixed/context"]
    monkeypatch.setattr("concord_paperclip.gateway.call", lambda command: copy.deepcopy(ctx))
    monkeypatch.setattr("concord_paperclip.gateway.native_backend", lambda config: backend)
    result = execute(config, {"action": "receive", "task_id": ctx["task_id"]})
    assert result["tests"]["status"] == "passed"
    assert backend.writes == []


def test_native_probe_does_not_invent_freshness_or_use_worker_oauth(native_setup, monkeypatch):
    from concord_paperclip.gateway import execute
    config, ctx, backend, _ = native_setup
    config["native_probe_command"] = ["/fixed/probe"]
    backend.agents = lambda: [{"id": ctx["profile"], "status": "idle", "adapterType": "codex_local"}]
    backend.active_runs = lambda: []
    stale = dict(observed_at=10, enrolled=True, environment_empty=True, credential_available=True,
                 provider_auth="unknown", provider_quota="unknown")
    monkeypatch.setattr("concord_paperclip.gateway.call", lambda *args: {ctx["profile"]: stale})
    monkeypatch.setattr("concord_paperclip.gateway.native_backend", lambda config: backend)
    result = execute(config, {"action": "probe"})[ctx["profile"]]
    assert evaluate(result, 100)["code"] == "STALE_PROBE"
    assert "oauth_present" not in result


@pytest.mark.parametrize("field,value", [("id", "foreign"), ("companyId", "foreign"),
                                         ("agentId", "foreign"), ("contextSnapshot", {"issueId": "foreign"})])
def test_recovery_rechecks_exact_run_binding(native_setup, monkeypatch, field, value):
    config, ctx, backend, _ = native_setup
    native.receive(config, ctx, backend, clean=lambda _: True)
    recovery_action(config, ctx, backend)
    row = copy.deepcopy(backend.rows[0])
    monkeypatch.setattr(backend, "run", lambda _: {**row, field: value})
    with pytest.raises(BridgeError, match="INVALID_TERMINAL_EVIDENCE"):
        native.resolve_recovery(config, ctx, backend)
    assert backend.writes == []


def repair_run(config, ctx, backend):
    recovery_action(config, ctx, backend)
    return {**backend.rows[0], "id": uid(), "createdAt": 13, "finishedAt": 14,
            "contextSnapshot": {"issueId": ctx["issue_id"], "wakeReason": "issue_disposition_repair",
                                "source": "issue.deliberate_wait_disposition_repair",
                                "recoveryActionId": backend.action["id"],
                                "dispositionRepairSourceRunId": backend.rows[0]["id"],
                                "retryOfRunId": backend.rows[0]["id"]}}


@pytest.mark.parametrize("status", ["in_progress", "in_review"])
def test_recovery_parks_exact_completed_run_atomically(native_setup, status):
    config, ctx, backend, _ = native_setup
    backend.current["status"] = status
    native.receive(config, ctx, backend)
    recovery_action(config, ctx, backend)
    assert native.resolve_recovery(config, ctx, backend)["state"] == "resolved"
    assert native.resolve_recovery(config, ctx, backend)["state"] == "clear"
    assert len(backend.writes) == 1
    assert backend.current["status"] == "in_review"
    assert backend.writes[0]["sourceIssueStatus"] == "in_review"


@pytest.mark.parametrize("status", ["todo", "backlog", "done", "cancelled", "blocked"])
def test_recovery_never_parks_other_status(native_setup, status):
    config, ctx, backend, _ = native_setup
    native.receive(config, ctx, backend)
    recovery_action(config, ctx, backend)
    backend.current["status"] = status
    with pytest.raises(BridgeError, match="RECOVERY_SCOPE"):
        native.resolve_recovery(config, ctx, backend)
    assert not backend.writes


@pytest.mark.parametrize("change", ["human", "source", "action", "origin", "failed", "owner"])
def test_untracked_terminal_continuation_never_imports_old_files(native_setup, change, monkeypatch):
    config, ctx, backend, _ = native_setup
    first = native.receive(config, ctx, backend)
    later = repair_run(config, ctx, backend)
    if change == "human":
        later["contextSnapshot"] = {"issueId": ctx["issue_id"], "wakeReason": "issue_commented"}
    elif change == "source":
        later["contextSnapshot"]["dispositionRepairSourceRunId"] = uid()
    elif change == "action":
        later["contextSnapshot"]["recoveryActionId"] = uid()
    elif change == "origin":
        later["contextSnapshot"]["source"] = "human"
    elif change == "failed":
        later["status"] = "failed"
    else:
        backend.action["ownerAgentId"] = uid()
    backend.rows = [later, *backend.rows]
    monkeypatch.setattr("concord_paperclip.gateway.verify", lambda *_: pytest.fail("obsolete receipt tested"))
    with pytest.raises((BridgeError, ValueError, TypeError)):
        native.receive(config, ctx, backend)
    assert native.Journal(config["receipt_root"]).record(ctx["task_id"]) == first["snapshot"]


@pytest.mark.parametrize("lock", ["executionRunId", "checkoutRunId"])
def test_recovery_refreshes_locks_after_verifier(native_setup, monkeypatch, lock):
    config, ctx, backend, _ = native_setup
    result = native.receive(config, ctx, backend)
    recovery_action(config, ctx, backend)
    def verify(*_):
        backend.current[lock] = uid()
        return result["tests"]
    monkeypatch.setattr("concord_paperclip.gateway.verify", verify)
    with pytest.raises(BridgeError, match="RECOVERY_SCOPE"):
        native.resolve_recovery(config, ctx, backend)
    assert not backend.writes
