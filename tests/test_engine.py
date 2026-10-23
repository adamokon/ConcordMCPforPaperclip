import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from concord_paperclip.engine import Engine
from concord_paperclip.policy import BridgeError, Principal, classify_failure, relative_path
from concord_paperclip.store import Store
from conftest import completed, running, submit


def test_submit_idempotency(setup):
    e, b, _ = setup
    a = submit(e)
    assert submit(e)["id"] == a["id"]
    e.drain()
    e.drain()
    assert b.creates == 1


def test_conflicting_key(setup):
    e, _, _ = setup
    submit(e)
    with pytest.raises(BridgeError, match="IDEMPOTENCY_CONFLICT"):
        submit(e, paths=["other.py"])


def test_create_loss_never_replays(setup):
    e, b, s = setup
    task = submit(e)
    b.drop_create_reply = True
    e.drain()
    assert e.inspect(task["id"])["state"] == "create_uncertain"
    restored = Engine(Store(s.path), b, Principal("owner"))
    restored.recover()
    restored.drain()
    assert b.creates == 1
    task = restored.inspect(task["id"])
    result = restored.adopt(task["id"], next(iter(b.rows)), task["version"])
    assert result["state"] == "backlog"


def test_concurrent_submit_and_drain(setup):
    e, b, _ = setup
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: submit(e), range(5)))
    assert len({r["id"] for r in results}) == 1
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lambda _: e.drain(), range(5)))
    assert b.creates == 1


def test_pending_creation_crash_quarantined(setup):
    e, b, s = setup
    t = submit(e)
    with s.transaction() as c:
        c.execute("UPDATE tasks SET state='creating' WHERE id=?", (t["id"],))
    assert e.recover()["quarantined"] == 1
    e.drain()
    assert b.creates == 0


def test_scope_overlap(setup):
    e, _, _ = setup
    submit(e, paths=["src/"])
    with pytest.raises(BridgeError, match="FILE_SCOPE_CONFLICT"):
        submit(e, "second", ["src/x.py"])
    assert submit(e, "third", ["src2/x.py"])


@pytest.mark.parametrize("path", ["../x", "/etc/passwd", "a/../b", "a//b", "./x", "a\\b", "*", ".git/config", ".env", "a\x00b"])
def test_bad_paths(path):
    with pytest.raises(BridgeError):
        relative_path(path)


def test_payload_budget_includes_envelope(setup):
    e, _, s = setup
    with pytest.raises(BridgeError, match="PAYLOAD_TOO_LARGE"):
        e.submit("oversize", "title", "x"*15990, "demo", ["main.py"])
    with s.connect() as c:
        assert c.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0


def test_no_implicit_ready(setup):
    e, b, _ = setup
    e.profiles[0]["ready_until"] = time.time()-1
    t = submit(e)
    e.drain()
    t = e.inspect(t["id"])
    with pytest.raises(BridgeError, match="NO_ELIGIBLE_PROFILE"):
        e.dispatch(t["id"], t["version"])
    assert b.patches == 0


def test_dispatch_uncertain_holds_profile_slot(setup):
    e, b, s = setup
    t = submit(e)
    e.drain()
    t = e.inspect(t["id"])
    b.drop_patch_reply = True
    with pytest.raises(BridgeError, match="DISPATCH_UNCERTAIN"):
        e.dispatch(t["id"], t["version"])
    e.recover()
    t2 = submit(e, "second", ["other.py"])
    e.drain()
    t2 = e.inspect(t2["id"])
    with pytest.raises(BridgeError, match="NO_ELIGIBLE_PROFILE"):
        e.dispatch(t2["id"], t2["version"])
    assert b.patches == 1
    with s.connect() as c:
        assert c.execute("SELECT state FROM attempts").fetchone()[0] == "uncertain"


def test_read_does_not_change_version_or_trigger(setup):
    e, b, s = setup
    t = submit(e)
    for _ in range(3):
        assert e.inspect(t["id"])["version"] == t["version"]
    assert not b.creates and not b.patches
    assert e.wait(t["id"], t["version"], 0)["changed"] is False


def test_stale_version(setup):
    e, _, _ = setup
    t = submit(e)
    e.drain()
    with pytest.raises(BridgeError, match="STALE_VERSION"):
        e.dispatch(t["id"], t["version"])


def test_identity_cannot_be_tool_argument(setup):
    e, b, s = setup
    t = submit(e)
    intruder = Engine(s, b, Principal("intruder", "worker"))
    with pytest.raises(BridgeError, match="FORBIDDEN"):
        intruder.inspect(t["id"])
    with pytest.raises(BridgeError, match="FORBIDDEN"):
        submit(intruder)


def test_worker_only_messages_coordinator_and_own_thread(setup):
    e, b, s = setup
    t = submit(e)
    worker = Engine(s, b, Principal("worker", "worker", (t["id"],)))
    question = worker.message("q", t["id"], "owner", "Which behavior?")
    assert question["state"] == "recorded"
    answer = e.message("a", t["id"], "worker", "Return False.", question["id"])
    assert worker.inspect(t["id"])["messages"][-1]["id"] == answer["id"]
    with pytest.raises(BridgeError, match="FORBIDDEN"):
        worker.message("bad", t["id"], "other", "Please deploy")
    assert worker.message("q", t["id"], "owner", "Which behavior?") == question


def test_no_false_terminal_or_auto_expiry(setup):
    e, b, s = setup
    t = running(e)
    with pytest.raises(BridgeError, match="INVALID_RUN_EVIDENCE"):
        e.observe(t["id"], {"issue_id": t["issue_id"], "status": "succeeded", "environment_removed": False})
    e.recover()
    with s.connect() as c:
        assert c.execute("SELECT state FROM attempts").fetchone()[0] == "running"


def test_delegation_scope_and_depth(setup):
    e, _, store = setup
    parent = submit(e, paths=["src/"])
    with pytest.raises(BridgeError, match="PARENT_NOT_PARKED"):
        submit(e, "not-parked", ["src/a.py"], parent_id=parent["id"])
    with store.transaction() as c:
        c.execute("UPDATE tasks SET state='review_ready' WHERE id=?", (parent["id"],))
    child = submit(e, "child", ["src/a.py"], parent_id=parent["id"])
    with pytest.raises(BridgeError, match="SCOPE_ESCALATION"):
        submit(e, "outside", ["outside.py"], parent_id=parent["id"])
    with pytest.raises(BridgeError, match="DELEGATION_DEPTH"):
        with store.transaction() as c:
            c.execute("UPDATE tasks SET state='review_ready' WHERE id=?", (child["id"],))
        submit(e, "deep", ["src/a.py"], parent_id=child["id"])


def test_batch_question_answer_transfers_verified_files(setup, tmp_path):
    e, b, s = setup
    t = completed(e, b)
    (tmp_path/"main.py").write_text("def f(): return False\n")
    e.collect(t["id"], tmp_path, ["main.py"])
    worker = Engine(s, b, Principal("worker", "worker", (t["id"],)))
    q = worker.message("q", t["id"], "owner", "False or exception?")
    a = e.message("a", t["id"], "worker", "False", q["id"])
    child = e.continuation("continue", t["id"], q["id"], a["id"])
    with s.connect() as c:
        spec = json.loads(c.execute("SELECT spec FROM tasks WHERE id=?", (child["id"],)).fetchone()[0])
    assert spec["inputs"]["main.py"].endswith("False\n")
    assert e.continuation("continue", t["id"], q["id"], a["id"])["id"] == child["id"]


def test_review_requires_artifacts_and_manifest(setup, tmp_path):
    e, b, _ = setup
    t = completed(e, b)
    with pytest.raises(BridgeError):
        e.review("bad", t["id"], t["version"], "bad", ["unittest"], "review")
    (tmp_path/"main.py").write_text("x=1\n")
    result = e.collect(t["id"], tmp_path, ["main.py"])
    t = e.inspect(t["id"])
    with pytest.raises(BridgeError, match="MANIFEST_MISMATCH"):
        e.review("wrong", t["id"], t["version"], "wrong", ["unittest"], "review")
    e.review("ok", t["id"], t["version"], result["digest"], ["python -m unittest"], "Operator tested")
    e.close_reviews()
    assert e.inspect(t["id"])["state"] == "complete"
    # Remote drift never automatically re-dispatches a reviewed task.
    b.rows[t["issue_id"]]["status"] = "todo"
    e.observe(t["id"])
    e.drain()
    assert e.inspect(t["id"])["state"] == "complete"
    assert b.creates == 1


def test_backup_and_unknown_schema(setup, tmp_path):
    e, _, s = setup
    t = submit(e)
    s.backup(str(tmp_path/"backup.db"))
    restored = Store(tmp_path/"backup.db")
    with restored.connect() as c:
        assert c.execute("SELECT id FROM tasks").fetchone()[0] == t["id"]
    with restored.connect() as c:
        c.execute("PRAGMA user_version=999")
    with pytest.raises(BridgeError, match="SCHEMA_VERSION"):
        Store(tmp_path/"backup.db")


@pytest.mark.parametrize("source,code,confirmed,expected", [
    ("proxy", "rate_limit_exceeded", True, "unknown"),
    ("model_provider", "RESOURCE_EXHAUSTED", True, "unknown"),
    ("model_provider", "quota_exceeded", False, "unknown"),
    ("model_provider", "quota_exceeded", True, "confirmed_quota"),
    ("model_provider", "invalid_grant", True, "authentication"),
    ("worker", "test_failed", True, "tests"),
])
def test_quota_classification(source, code, confirmed, expected):
    assert classify_failure(source, code, confirmed) == expected
