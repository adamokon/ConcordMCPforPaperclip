"""Opt-in partial harvesting and profile cleanup in the existing receiver."""

import json
import sqlite3
from pathlib import Path

from .automation import gateway
from .partial_store import ensure, save
from .policy import BridgeError


def read_context(config, task_id):
    db = sqlite3.connect(Path(config["database"]).as_uri() + "?mode=ro", uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        t = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        a = db.execute(
            "SELECT * FROM attempts WHERE task_id=? ORDER BY number DESC LIMIT 1", (task_id,)
        ).fetchone()
        if not t or t["owner"] != config["principal"] or not a or a["state"] != "terminal" or not a["run_id"]:
            raise BridgeError("PARTIAL_TERMINAL_REQUIRED")
        return dict(
            task_id=task_id,
            issue_id=t["issue_id"],
            run_id=a["run_id"],
            agent_id=a["profile"],
            state=t["state"],
            paths=json.loads(t["spec"])["paths"],
        )
    finally:
        db.close()


def cycle(engine, config):
    policy = config.get("partial_policy", {})
    if policy.get("enabled") is not True:
        return []
    engine.actor.require("coordinator")
    with engine.store.transaction() as c:
        ensure(c)
        rows = [
            dict(r)
            for r in c.execute(
                "SELECT * FROM tasks WHERE owner=? AND state IN "
                "('execution_failed','partial_ready','cancelled')",
                (engine.actor.name,),
            )
        ]
    result = []
    for t in rows:
        if json.loads(t["spec"])["repo"] not in policy.get("allowed_repos", []) and t["id"] not in policy.get(
            "historical_tasks", []
        ):
            continue
        with engine.store.connect() as c:
            done = c.execute(
                "SELECT 1 FROM audit WHERE task_id=? AND event='partial_profile_recovered'", (t["id"],)
            ).fetchone()
        with engine.store.connect() as c:
            exported = c.execute(
                "SELECT 1 FROM audit WHERE task_id=? AND event='partial_exported'", (t["id"],)
            ).fetchone()
        if done and exported:
            continue
        try:
            if done:
                exported_result = gateway(config, {"action": "partial-export", "task_id": t["id"]})
                if exported_result.get("export_ready") is not True:
                    raise BridgeError("PARTIAL_EXPORT_NOT_READY")
                with engine.store.transaction() as c:
                    engine.store.audit(c, engine.actor.name, t["id"], "partial_exported", {})
                result.append({"id": t["id"], "export_ready": True})
                continue
            record = gateway(config, {"action": "partial-collect", "task_id": t["id"]})
            if record.get("pending"):
                result.append({"id": t["id"], "state": "pending"})
                continue
            out = save(engine, t["id"], record)
            cleanup = gateway(config, {"action": "partial-cleanup", "task_id": t["id"]})
            if cleanup.get("profile_ready") is not True:
                raise BridgeError("PARTIAL_PROFILE_NOT_READY")
            if cleanup.get("export_ready") is not True:
                raise BridgeError("PARTIAL_EXPORT_NOT_READY")
            with engine.store.transaction() as c:
                engine.store.audit(c, engine.actor.name, t["id"], "partial_exported", {})
                engine.store.audit(
                    c,
                    engine.actor.name,
                    t["id"],
                    "partial_profile_recovered",
                    {"run_id": record["record"]["binding"]["run_id"], "digest": out["digest"]},
                )
            result.append({**out, "profile_ready": True})
        except (BridgeError, ValueError, KeyError, TypeError) as e:
            result.append({"id": t["id"], "code": getattr(e, "code", "INVALID_PARTIAL_RECEIPT")})
    return result
