"""Append-only receipt of partial files, separate from accepted full manifests."""

import base64
import hashlib
import json

from .artifacts import public_manifest
from .partial_result import validate_partial_record
from .policy import BridgeError, tokenish
from .store import canonical


def ensure(c):
    c.execute(
        "CREATE TABLE IF NOT EXISTS partial_receipts ("
        "task_id TEXT NOT NULL,run_id TEXT NOT NULL,record TEXT NOT NULL,snapshot TEXT NOT NULL,"
        "PRIMARY KEY(task_id,run_id))"
    )


def save(engine, task_id, result):
    engine.actor.require("coordinator")
    record, snap = result["record"], result["snapshot"]
    with engine.store.transaction() as c:
        ensure(c)
        t = engine._task(c, task_id)
        if t["state"] not in {"execution_failed", "partial_ready", "cancelled"}:
            raise BridgeError("PARTIAL_STATE_REQUIRED")
        a = c.execute(
            "SELECT * FROM attempts WHERE task_id=? ORDER BY number DESC LIMIT 1", (task_id,)
        ).fetchone()
        if not a or a["state"] != "terminal" or a["run_id"] != record["binding"]["run_id"]:
            raise BridgeError("PARTIAL_TERMINAL_REQUIRED")
        evidence = json.loads(a["evidence"] or "{}")
        if evidence.get("environment_removed") is not True:
            raise BridgeError("PARTIAL_CLEANUP_REQUIRED")
        expected = dict(
            task_id=task_id,
            issue_id=t["issue_id"],
            run_id=a["run_id"],
            agent_id=a["profile"],
            paths=json.loads(t["spec"])["paths"],
        )
        if not validate_partial_record(record, expected):
            raise BridgeError("INVALID_PARTIAL_RECORD")
        if (
            snap["digest"] != record["snapshot_digest"]
            or hashlib.sha256(canonical(snap["manifest"]).encode()).hexdigest() != snap["digest"]
            or any(
                snap["manifest"].get(k) != expected[k] for k in ["task_id", "issue_id", "run_id", "agent_id"]
            )
            or sorted(f["path"] for f in snap["manifest"]["files"]) != sorted(record["present_paths"])
        ):
            raise BridgeError("PARTIAL_MANIFEST_MISMATCH")
        total = 0
        for f in snap["manifest"]["files"]:
            data = base64.b64decode(f["content_base64"], validate=True)
            total += len(data)
            if (
                len(data) != f["size"]
                or len(data) > 262144
                or total > 1048576
                or hashlib.sha256(data).hexdigest() != f["sha256"]
                or tokenish(data)
            ):
                raise BridgeError("UNSAFE_PARTIAL_ARTIFACT")
        old = c.execute(
            "SELECT record,snapshot FROM partial_receipts WHERE task_id=? AND run_id=?",
            (task_id, a["run_id"]),
        ).fetchone()
        if old:
            if old["record"] != canonical(record) or old["snapshot"] != canonical(snap):
                raise BridgeError("PARTIAL_RECEIPT_CONFLICT")
        else:
            c.execute(
                "INSERT INTO partial_receipts VALUES(?,?,?,?)",
                (task_id, a["run_id"], canonical(record), canonical(snap)),
            )
            if t["state"] not in {"cancelled", "complete"}:
                engine._set(c, task_id, "partial_ready")
            engine.store.audit(
                c,
                engine.actor.name,
                task_id,
                "partial_received",
                {"run_id": a["run_id"], "digest": snap["digest"], "complete": False},
            )
    return {
        "id": task_id,
        "state": "partial_ready" if t["state"] not in {"cancelled", "complete"} else t["state"],
        "partial": True,
        "digest": snap["digest"],
    }


def read(engine, task_id, include_content=False):
    with engine.store.connect() as c:
        engine._task(c, task_id)
        exists = c.execute("SELECT 1 FROM sqlite_master WHERE name='partial_receipts'").fetchone()
        row = (
            c.execute(
                "SELECT record,snapshot FROM partial_receipts WHERE task_id=? ORDER BY rowid DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            if exists
            else None
        )
    if not row:
        raise BridgeError("NO_PARTIAL_RECEIPT")
    snap = json.loads(row["snapshot"])
    return {
        "partial": True,
        "complete": False,
        "record": json.loads(row["record"]),
        "snapshot": snap if include_content else public_manifest(snap),
    }
