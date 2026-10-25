"""Real snapshots and SQLite; fixed gateway effects are counted, never inferred."""

import copy
import json
import subprocess
import uuid

import pytest

from conftest import running
from concord_paperclip import partial_cycle, partial_store, worker_io
from concord_paperclip.partial_io import capture_partial
from concord_paperclip.policy import BridgeError


def binding():
    return {k: str(uuid.uuid4()) for k in ("task_id", "issue_id", "run_id", "agent_id")}


def failed(setup, tmp_path):
    engine, backend, store = setup
    t = running(engine)
    run = str(uuid.uuid4())
    engine.observe(
        t["id"],
        dict(
            issue_id=t["issue_id"],
            run_id=run,
            agent_id=backend.profile,
            status="failed",
            environment_removed=True,
        ),
    )
    with store.transaction() as c:
        engine._set(c, t["id"], "execution_failed")
    b = dict(task_id=t["id"], issue_id=t["issue_id"], run_id=run, agent_id=backend.profile)
    (tmp_path / "main.py").write_text("answer = 42\n")
    return engine, store, t["id"], capture_partial(tmp_path, ["main.py"], b)


def test_snapshot_partitions_and_ignores_unspecified_files(tmp_path):
    (tmp_path / "main.py").write_text("answer = 42\n")
    (tmp_path / "private.txt").write_text("not delegated")
    result = capture_partial(tmp_path, ["main.py", "RESULT.txt"], binding())
    assert result["record"]["missing_paths"] == ["RESULT.txt"]
    assert result["record"]["complete"] is False
    assert [f["path"] for f in result["snapshot"]["manifest"]["files"]] == ["main.py"]


@pytest.mark.parametrize("kind", ["symlink", "dangling", "hardlink", "fifo", "secret", "private"])
def test_unsafe_partial_never_received(tmp_path, kind):
    p = tmp_path / "main.py"
    if kind in {"symlink", "dangling"}:
        target = tmp_path / "target"
        if kind == "symlink":
            target.write_text("x=1")
        p.symlink_to(target)
    elif kind == "hardlink":
        p.write_text("x=1")
        (tmp_path / "other").hardlink_to(p)
    elif kind == "fifo":
        import os

        os.mkfifo(p)
    elif kind == "secret":
        p.write_text('token="ghp_' + "Z" * 30 + '"')
    else:
        p = tmp_path / ".env.py"
        p.write_text("x=1")
    with pytest.raises(BridgeError):
        capture_partial(tmp_path, [p.name], binding())


def test_receipt_idempotent_separate_from_success_and_claims_retained(setup, tmp_path):
    e, s, tid, result = failed(setup, tmp_path)
    first = partial_store.save(e, tid, result)
    assert first == partial_store.save(e, tid, result)
    assert e.inspect(tid)["state"] == "partial_ready"
    with s.connect() as c:
        assert c.execute("SELECT count(*) FROM manifests").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM claims").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM audit WHERE event='partial_received'").fetchone()[0] == 1
    visible = partial_store.read(e, tid)
    assert visible["partial"] is True and visible["complete"] is False
    assert "content_base64" not in visible["snapshot"]["manifest"]["files"][0]
    assert partial_store.read(e, tid, True)["snapshot"] == result["snapshot"]
    (tmp_path / "main.py").write_text("changed = True\n")
    changed = capture_partial(tmp_path, ["main.py"], result["record"]["binding"])
    with pytest.raises(BridgeError, match="PARTIAL_RECEIPT_CONFLICT"):
        partial_store.save(e, tid, changed)


def test_read_does_not_create_partial_schema(setup):
    e, _, s = setup
    t = running(e)
    with pytest.raises(BridgeError, match="NO_PARTIAL_RECEIPT"):
        partial_store.read(e, t["id"])
    with s.connect() as c:
        assert (
            c.execute("SELECT count(*) FROM sqlite_master WHERE name='partial_receipts'").fetchone()[0] == 0
        )


def test_cancelled_not_reopened(setup, tmp_path):
    e, s, tid, r = failed(setup, tmp_path)
    with s.transaction() as c:
        c.execute("UPDATE tasks SET state='cancelled' WHERE id=?", (tid,))
        c.execute("DELETE FROM claims WHERE task_id=?", (tid,))
    assert partial_store.save(e, tid, r)["state"] == "cancelled"
    assert e.inspect(tid)["state"] == "cancelled"
    with s.connect() as c:
        assert c.execute("SELECT count(*) FROM claims").fetchone()[0] == 0


@pytest.mark.parametrize("fault", ["binding", "digest", "bytes", "cleanup", "state"])
def test_receipt_refuses_mismatch_before_state_change(setup, tmp_path, fault):
    e, s, tid, r = failed(setup, tmp_path)
    r = copy.deepcopy(r)
    if fault == "binding":
        r["record"]["binding"]["agent_id"] = str(uuid.uuid4())
    elif fault == "digest":
        r["snapshot"]["digest"] = "f" * 64
    elif fault == "bytes":
        r["snapshot"]["manifest"]["files"][0]["content_base64"] = "eA=="
    else:
        with s.transaction() as c:
            if fault == "cleanup":
                c.execute("UPDATE attempts SET evidence='{}' WHERE task_id=?", (tid,))
            else:
                c.execute("UPDATE tasks SET state='complete' WHERE id=?", (tid,))
    with pytest.raises(BridgeError):
        partial_store.save(e, tid, r)
    with s.connect() as c:
        exists = c.execute("SELECT 1 FROM sqlite_master WHERE name='partial_receipts'").fetchone()
        if exists:
            assert c.execute("SELECT count(*) FROM partial_receipts").fetchone()[0] == 0


def test_cycle_cleanup_after_durable_receipt_and_once(setup, tmp_path, monkeypatch):
    e, s, tid, r = failed(setup, tmp_path)
    calls = []

    def gateway(cfg, q):
        calls.append(q["action"])
        if q["action"] == "partial-collect":
            return r
        with s.connect() as c:
            assert c.execute("SELECT count(*) FROM partial_receipts").fetchone()[0] == 1
        return {"profile_ready": True, "export_ready": True}

    monkeypatch.setattr(partial_cycle, "gateway", gateway)
    cfg = {"partial_policy": {"enabled": True, "allowed_repos": ["demo"]}}
    assert partial_cycle.cycle(e, cfg)[0]["profile_ready"] is True
    assert partial_cycle.cycle(e, cfg) == []
    assert calls == ["partial-collect", "partial-cleanup"]


def test_cycle_bad_receipt_cannot_clear_profile(setup, tmp_path, monkeypatch):
    e, _, _, r = failed(setup, tmp_path)
    r["record"]["snapshot_digest"] = "a" * 64
    calls = []
    monkeypatch.setattr(partial_cycle, "gateway", lambda c, q: calls.append(q["action"]) or r)
    result = partial_cycle.cycle(e, {"partial_policy": {"enabled": True, "allowed_repos": ["demo"]}})
    assert result[0]["code"] == "PARTIAL_MANIFEST_MISMATCH"
    assert calls == ["partial-collect"]


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "early",
        "auth",
        "quota",
        "quota429",
        "security",
        "busy",
        "unknown",
        "zero",
        "false",
        "list",
        "dict",
        "null",
        "missing",
    ],
)
def test_real_worker_observation_gate(tmp_path, monkeypatch, fault):
    b = binding()
    root = tmp_path / "workspaces" / b["run_id"]
    root.mkdir(parents=True)
    (root / "main.py").write_text("answer = 42\n")
    raw = dict(run_id=b["run_id"], status="error", exit_code=1, denied_actions=[], elapsed_seconds=484.289)
    if fault == "early":
        raw["elapsed_seconds"] = 479.9
    if fault == "security":
        raw["denied_actions"] = ["unapproved"]
    (root / "result.json").write_text(json.dumps(raw))
    cli = dict(
        status="SUCCESS",
        response={"zero": 0, "false": False, "list": [], "dict": {}, "null": None}.get(fault, ""),
    )
    if fault == "missing":
        del cli["response"]
    (root / "cli-output.json").write_text(json.dumps(cli))
    (root / "cli-stderr.log").write_text(
        "timeout480s "
        + {"auth": "unauthorized", "quota": "RESOURCE_EXHAUSTED", "quota429": "HTTP 429"}.get(fault, "")
    )
    items = [{"metadata": {"labels": {"agy.binzoo.io/run-id": b["run_id"]}}}] if fault == "busy" else []
    monkeypatch.setattr(
        worker_io.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess([], 0, json.dumps({"items": items}).encode()),
    )
    cfg = dict(
        kubectl="/fixed/kubectl",
        profiles={"p": dict(home=str(tmp_path), kubeconfig="/fixed/config", namespace="test")},
    )
    req = dict(
        action="partial",
        profile="p",
        run_id=b["run_id"],
        paths=["main.py", "RESULT.txt"],
        context=b,
        deadline_seconds=480,
        producer_verified=fault != "unknown",
        task_cancelled=False,
        native_status="failed",
    )
    if fault is None:
        assert worker_io.execute(cfg, req)["record"]["missing_paths"] == ["RESULT.txt"]
    elif fault == "busy":
        assert worker_io.execute(cfg, req) == {"pending": True}
    else:
        with pytest.raises(BridgeError, match="PARTIAL_INELIGIBLE"):
            worker_io.execute(cfg, req)


def test_export_recovery_does_not_clear_new_profile(setup, tmp_path, monkeypatch):
    e, s, tid, r = failed(setup, tmp_path)
    partial_store.save(e, tid, r)
    with s.transaction() as c:
        e.store.audit(c, e.actor.name, tid, "partial_profile_recovered", {})
    calls = []
    monkeypatch.setattr(
        partial_cycle, "gateway", lambda c, q: calls.append(q["action"]) or {"export_ready": True}
    )
    cfg = {"partial_policy": {"enabled": True, "allowed_repos": ["demo"]}}
    assert partial_cycle.cycle(e, cfg) == [{"id": tid, "export_ready": True}]
    assert partial_cycle.cycle(e, cfg) == []
    assert calls == ["partial-export"]


def test_lost_cleanup_response_reuses_receipt_without_model_retry(setup, tmp_path, monkeypatch):
    e, s, tid, r = failed(setup, tmp_path)
    effects = []
    cleanup_calls = []

    def gateway(cfg, q):
        if q["action"] == "partial-collect":
            return r
        cleanup_calls.append(q["action"])
        if not effects:
            effects.append("cleared-exact-terminal-profile")
            raise BridgeError("GATEWAY_UNAVAILABLE")
        return {"profile_ready": True, "export_ready": True}

    monkeypatch.setattr(partial_cycle, "gateway", gateway)
    cfg = {"partial_policy": {"enabled": True, "allowed_repos": ["demo"]}}
    assert partial_cycle.cycle(e, cfg)[0]["code"] == "GATEWAY_UNAVAILABLE"
    assert e.inspect(tid)["state"] == "partial_ready"
    assert partial_cycle.cycle(e, cfg)[0]["profile_ready"] is True
    assert partial_cycle.cycle(e, cfg) == []
    assert effects == ["cleared-exact-terminal-profile"]
    assert cleanup_calls == ["partial-cleanup", "partial-cleanup"]
    with s.connect() as c:
        assert c.execute("SELECT count(*) FROM partial_receipts").fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM attempts").fetchone()[0] == 1


def test_fixed_host_rejects_caller_evidence_and_export_is_distinct(monkeypatch):
    from concord_paperclip import partial_host
    from concord_paperclip import gateway as fixed_gateway

    b = binding()
    context = dict(b, paths=["main.py"], state="cancelled")
    calls = []

    def call(command, q):
        calls.append(q)
        if command[0] == "/fixed/context":
            return context
        if q["action"] == "inspect":
            return dict(run_id=b["run_id"], agent_id=b["agent_id"], status="failed", producer_verified=True)
        return {"export_ready": True}

    monkeypatch.setattr(partial_host, "call", call)
    monkeypatch.setattr(
        fixed_gateway,
        "worker",
        lambda c, q: pytest.fail("Export must use secured receipt, never reread workspace"),
    )
    cfg = {
        "partial": {
            "enabled": True,
            "context_command": ["/fixed/context"],
            "native_command": ["/fixed/native"],
        },
        "profiles": {b["agent_id"]: "p"},
    }
    with pytest.raises(BridgeError, match="INVALID_REQUEST"):
        partial_host.execute(
            cfg, dict(action="partial-cleanup", task_id=b["task_id"], environment_removed=True)
        )
    assert calls == []
    assert partial_host.execute(cfg, dict(action="partial-export", task_id=b["task_id"])) == {
        "export_ready": True
    }
    assert calls[-1]["action"] == "export"
