import json
import uuid

import pytest

from concord_paperclip.policy import BridgeError
from conftest import running


@pytest.mark.parametrize("remote,locked", [("done", False), ("blocked", False), ("cancelled", True)])
def test_failed_claims_retained_without_unlocked_native_cancellation(setup, remote, locked):
    e, b, _ = setup
    t = running(e)
    b.rows[t["issue_id"]].update(status=remote, executionRunId="busy" if locked else None)
    with pytest.raises(BridgeError, match="REMOTE_CANCELLATION_REQUIRED"):
        e.reconcile_cancelled(t["id"], t["version"])


def test_explicit_cancelled_readback_retains_failure_history(setup):
    e, b, store = setup
    t = running(e)
    t = e.observe(t["id"], {"issue_id": t["issue_id"], "agent_id": b.profile,
                           "run_id": str(uuid.uuid4()), "status": "failed", "environment_removed": True})
    with store.transaction() as c:
        e._set(c, t["id"], "execution_failed")
        before = dict(c.execute("SELECT * FROM attempts WHERE task_id=?", (t["id"],)).fetchone())
    t = e.inspect(t["id"])
    b.rows[t["issue_id"]].update(status="cancelled", executionRunId=None, checkoutRunId=None)
    assert e.reconcile_cancelled(t["id"], t["version"])["state"] == "cancelled"
    with store.connect() as c:
        assert dict(c.execute("SELECT * FROM attempts WHERE task_id=?", (t["id"],)).fetchone()) == before
        assert json.loads(before["evidence"])["status"] == "failed"
        assert c.execute("SELECT count(*) FROM claims WHERE task_id=?", (t["id"],)).fetchone()[0] == 0
