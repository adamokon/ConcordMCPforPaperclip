"""Durable non-model coordinator wake; uncertain creates are never retried."""

import json
import math
import time

from .policy import BridgeError


def wake(engine, config, marker):
    if not config.get("native_agent_id"):
        return {"mode": "manual_drain", "running": False}
    require_coordinator(engine.backend, config)
    # Journal this separate non-idempotent create. A lost response stays uncertain.
    with engine.store.transaction() as c:
        old = engine._operation(c, "wake:" + marker, "wake", {"marker": marker}, marker)
        if old:
            return {"mode": "native", "state": old["state"]}
        c.execute("UPDATE operations SET state='in_flight' WHERE owner=? AND key=?",
                  (engine.actor.name, "wake:" + marker))
    try:
        issue = engine.backend.wake_coordinator(config["native_agent_id"], marker)
    except Exception:
        return {"mode": "native", "state": "uncertain", "running": False}
    with engine.store.transaction() as c:
        c.execute("UPDATE operations SET state='done',result=? WHERE owner=? AND key=?",
                  (json.dumps({"issue_id": issue["id"]}), engine.actor.name, "wake:" + marker))
    return {"mode": "native", "state": "queued", "issue_id": issue["id"]}


def require_coordinator(backend, config):
    """A hidden roster requires fresh metadata from the fixed trusted gateway."""
    identity = config["native_agent_id"]
    roster = backend.agents()
    own = next((a for a in roster if a.get("id") == identity), None)
    if own is not None:
        if own.get("adapterType") != "process":
            raise BridgeError("NON_MODEL_COORDINATOR_REQUIRED")
        return
    from .automation import gateway
    proof = gateway(config, {"action": "probe"}).get("_coordinator")
    if not isinstance(proof, dict):
        raise BridgeError("NON_MODEL_COORDINATOR_REQUIRED")
    observed = proof.get("observed_at")
    now = time.time()
    if (proof.get("id") != identity or proof.get("company_id") != config["company_id"]
            or proof.get("project_id") != config["project_id"] or proof.get("adapter_type") != "process"
            or isinstance(observed, bool) or not isinstance(observed, (int, float))
            or not math.isfinite(observed) or not 0 <= now - observed <= 60):
        raise BridgeError("NON_MODEL_COORDINATOR_REQUIRED")
