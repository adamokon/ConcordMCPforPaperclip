"""A retry must not receive another run's files or infer the latest run."""

import pytest

from concord_paperclip import gateway
from concord_paperclip.policy import BridgeError


TASK = "11111111-1111-4111-8111-111111111111"
BOUND = "22222222-2222-4222-8222-222222222222"
OLD = "33333333-3333-4333-8333-333333333333"


@pytest.mark.parametrize("bound", [BOUND, None])
def test_receipt_uses_only_trusted_existing_run_binding(monkeypatch, bound):
    context = {"task_id": TASK, "issue_id": "issue", "state": "running",
               "created": 123, "profile": "agent", "run_id": bound, "paths": ["result.py"]}
    requests = []

    def call(command, request=None, timeout=25):
        if command[0] == "context":
            return context
        requests.append(request)
        # The backend has selected the scoped cancelled run; no files accepted.
        return {"id": bound or OLD, "status": "cancelled"}

    monkeypatch.setattr(gateway, "call", call)
    monkeypatch.setattr(gateway, "worker", lambda *_: {"environment_removed": True})
    result = gateway.execute({"context_command": ["context"], "telemetry_command": ["telemetry"],
                              "profiles": {"agent": "profile"}}, {"action": "receive", "task_id": TASK})
    assert requests == [{"action": "run", "issue_id": "issue", "agent_id": "agent", "after": 123,
                         **({"run_id": BOUND} if bound else {})}]
    assert result["evidence"]["run_id"] == (bound or OLD)
    assert result["failure"] == "cancelled"


def test_wrong_run_returned_for_binding_is_rejected(monkeypatch):
    context = {"task_id": TASK, "issue_id": "issue", "state": "running", "created": 123,
               "profile": "agent", "run_id": BOUND}
    monkeypatch.setattr(gateway, "call", lambda command, *args:
                        context if command[0] == "context" else {"id": OLD, "status": "succeeded"})
    with pytest.raises(BridgeError, match="RUN_MISMATCH"):
        gateway.execute({"context_command": ["context"], "telemetry_command": ["telemetry"],
                         "profiles": {"agent": "profile"}}, {"action": "receive", "task_id": TASK})


def test_caller_cannot_supply_run_binding():
    with pytest.raises(BridgeError, match="INVALID_REQUEST"):
        gateway.execute({}, {"action": "receive", "task_id": TASK, "run_id": BOUND})
