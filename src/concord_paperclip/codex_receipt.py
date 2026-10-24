"""Fixed native receiver. No scheduling and no commands or paths from the model.

The privileged gateway owns the config, /proc visibility and journal. Only public
allowlisted artifacts cross its boundary. The platform remains the run authority.
"""

import errno
import json
import math
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .artifacts import snapshot
from .policy import BridgeError, relative_path
from .store import canonical

TERMINAL = {"succeeded", "failed", "cancelled", "timed_out"}


def stamp(value):
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isfinite(value):
            return float(value)
    raise BridgeError("INVALID_RUN_TIME")


def uuid_value(value):
    try:
        if not isinstance(value, str) or str(uuid.UUID(value)) != value:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise BridgeError("INVALID_UUID") from None
    return value


def processes_empty(run_id, proc_root="/proc", executor_uid=None):
    """Kernel status UID domain, never directory ownership. Errors fail closed."""
    if executor_uid is not None and (type(executor_uid) is not int or executor_uid < 1):
        raise BridgeError("INVALID_EXECUTOR_UID")
    marker = ("PAPERCLIP_RUN_ID=" + uuid_value(run_id)).encode()
    try:
        for entry in Path(proc_root).iterdir():
            if not entry.name.isdecimal():
                continue
            try:
                if executor_uid is not None:
                    fields = {}
                    for line in (entry / "status").read_text().splitlines():
                        key, sep, value = line.partition(":")
                        if sep and key in {"Uid", "NoNewPrivs", "CapEff", "CapPrm", "CapAmb"}:
                            if key in fields:
                                raise ValueError()
                            fields[key] = value.split()
                    uids = fields.get("Uid", [])
                    if len(uids) != 4 or any(not x.isdecimal() for x in uids):
                        raise ValueError()
                    if executor_uid not in [int(x) for x in uids]:
                        continue
                    if fields.get("NoNewPrivs") != ["1"]:
                        raise ValueError()
                    for key in ("CapEff", "CapPrm", "CapAmb"):
                        value = fields.get(key, [])
                        if len(value) != 1 or not value[0] or any(
                                x not in "0123456789abcdefABCDEF" for x in value[0]) or int(value[0], 16):
                            raise ValueError()
                data = (entry / "environ").read_bytes()
            except OSError as error:
                if error.errno in {errno.ENOENT, errno.ESRCH}:
                    continue
                raise
            if marker in data.split(b"\0"):
                return False
    except (OSError, ValueError, UnicodeError):
        raise BridgeError("PROCESS_VISIBILITY_REQUIRED") from None
    return True


def cleanup(config, profile, run_id):
    uid = config["profiles"][profile].get("executor_uid")
    return processes_empty(run_id) if uid is None else processes_empty(run_id, executor_uid=uid)


class Journal:
    def __init__(self, root):
        root = Path(root)
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = root / "native.sqlite3"
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        with self.connect() as c:
            c.execute("CREATE TABLE IF NOT EXISTS receipts (task TEXT PRIMARY KEY, binding TEXT NOT NULL, "
                      "run TEXT NOT NULL, record TEXT, recovery TEXT)")

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA synchronous=FULL")
        try:
            with c:
                yield c
        finally:
            c.close()

    def pin(self, context, runs):
        binding = canonical({k: context[k] for k in
                             ("task_id", "issue_id", "profile", "company_id", "project_id", "attempt_id", "created")})
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT * FROM receipts WHERE task=?", (context["task_id"],)).fetchone()
            if row and row["binding"] != binding:
                raise BridgeError("RECEIPT_BINDING_CHANGED")
            if row:
                selected = next((r for r in runs if r["id"] == row["run"]), None)
                if not selected:
                    raise BridgeError("PINNED_RUN_UNAVAILABLE")
            else:
                if not runs:
                    return None
                selected = min(runs, key=lambda r: (stamp(r["createdAt"]), r["id"]))
                c.execute("INSERT INTO receipts(task,binding,run) VALUES(?,?,?)",
                          (context["task_id"], binding, selected["id"]))
            if context.get("run_id") and context["run_id"] != selected["id"]:
                raise BridgeError("RUN_MISMATCH")
            if any(r["id"] != selected["id"] and r["status"] not in TERMINAL for r in runs):
                raise BridgeError("OTHER_RUN_ACTIVE")
            return selected

    def record(self, task_id, value=None):
        with self.connect() as c:
            row = c.execute("SELECT record FROM receipts WHERE task=?", (task_id,)).fetchone()
            if not row:
                raise BridgeError("PIN_REQUIRED")
            if value is not None:
                encoded = canonical(value)
                if row["record"] and row["record"] != encoded:
                    raise BridgeError("SNAPSHOT_CHANGED")
                c.execute("UPDATE receipts SET record=? WHERE task=?", (encoded, task_id))
                return value
            return json.loads(row["record"]) if row["record"] else None


def bound_issue(config, context, backend):
    for key in ("task_id", "issue_id", "profile", "company_id", "project_id", "attempt_id"):
        uuid_value(context[key])
    if context["company_id"] != config["company_id"] or context["project_id"] != config["project_id"]:
        raise BridgeError("CONTEXT_SCOPE_MISMATCH")
    issue = backend.issue(context["issue_id"])
    if (issue.get("projectId") != config["project_id"] or issue.get("companyId") != config["company_id"]
            or issue.get("assigneeAgentId") not in {context["profile"], None}
            or context["task_id"] not in (issue.get("description") or "")):
        raise BridgeError("ISSUE_SCOPE_MISMATCH")
    return issue


def receive(config, context, backend, clean=None):
    clean = clean or (lambda run_id: cleanup(config, context["profile"], run_id))
    issue = bound_issue(config, context, backend)
    profile = config["profiles"][context["profile"]]
    if profile.get("adapter_type") != "codex_local":
        raise BridgeError("UNSUPPORTED_ADAPTER")
    # This supported endpoint is bounded; truncation cannot establish absence.
    rows = backend.request("GET", backend.company_path("heartbeat-runs") + "?agentId=" +
                           backend.segment(context["profile"]) + "&limit=1000")
    if not isinstance(rows, list) or len(rows) >= 1000:
        raise BridgeError("RUN_TELEMETRY_INCOMPLETE")
    runs = []
    for row in rows:
        ctx = row.get("contextSnapshot") or {}
        if (ctx.get("issueId") or ctx.get("taskId")) != context["issue_id"]:
            continue
        if row.get("companyId") != config["company_id"] or row.get("agentId") != context["profile"]:
            raise BridgeError("RUN_MISMATCH")
        uuid_value(row["id"])
        if stamp(row["createdAt"]) >= stamp(context["created"]):
            runs.append(row)
    journal = Journal(config["receipt_root"])
    run = journal.pin(context, runs)
    if not run or run["status"] not in TERMINAL:
        return {"pending": True}
    if repair_requested(run.get("contextSnapshot") or {}):
        raise BridgeError("UNTRACKED_NATIVE_CONTINUATION")
    for other in runs:
        if other["id"] == run["id"]:
            continue
        fresh_other = backend.run(other["id"])
        if fresh_other != other or fresh_other.get("status") != "succeeded":
            raise BridgeError("UNTRACKED_NATIVE_CONTINUATION")
        validate_repair(config, backend, fresh_other, run, issue, active_only=False)
        if not clean(other["id"]):
            raise BridgeError("OTHER_RUN_ACTIVE")
    # Refresh exact run, rather than trusting a possibly stale list projection.
    fresh = backend.run(run["id"])
    if any(fresh.get(k) != run.get(k) for k in ("id", "companyId", "agentId", "contextSnapshot", "status")):
        raise BridgeError("RUN_TELEMETRY_CHANGED")
    if not fresh.get("finishedAt") or stamp(fresh["finishedAt"]) < stamp(run["createdAt"]):
        raise BridgeError("INVALID_TERMINAL_EVIDENCE")
    if issue.get("executionRunId") or issue.get("checkoutRunId") or not clean(run["id"]):
        return {"pending": True}
    evidence = {"issue_id": context["issue_id"], "agent_id": context["profile"], "run_id": run["id"],
                "status": run["status"], "environment_removed": True}
    if run["status"] != "succeeded":
        return {"evidence": evidence, "failure": run["status"]}
    record = journal.record(context["task_id"])
    if record is None:
        paths = context["paths"]
        if not isinstance(paths, list) or any(relative_path(p).endswith("/") for p in paths):
            raise BridgeError("AUTOMATIC_RECEIPT_REQUIRES_EXACT_PATHS")
        binding = {"task_id": context["task_id"], "issue_id": context["issue_id"],
                   "agent_id": context["profile"], "run_id": run["id"]}
        record = snapshot(Path(profile["artifact_base"]) / run["id"], paths, paths, binding)
        journal.record(context["task_id"], record)
    # A fresh cleanup observation is mandatory even when reusing a pinned snapshot.
    after = backend.issue(context["issue_id"])
    if after.get("executionRunId") or after.get("checkoutRunId") or not clean(run["id"]):
        return {"pending": True}
    return {"evidence": evidence, "snapshot": record, "tests": native_verify(config, record),
            "native_review_required": True}


def probe(config, backend):
    from .gateway import call
    # Fixed operator-owned credential/availability probe, independent of AGY HOME.
    external = call(config["native_probe_command"], {"action": "probe"})
    roster = {r["id"]: r for r in backend.agents()}
    live = backend.active_runs()
    result = {}
    for identity, profile in config["profiles"].items():
        if profile.get("adapter_type") != "codex_local":
            continue
        item = external.get(identity, {})
        agent = roster.get(identity, {})
        result[identity] = {**item, "adapter_type": agent.get("adapterType"),
                            "agent_status": agent.get("status"),
                            "active_runs": sum(r.get("agentId") == identity for r in live)}
    if config.get("native_agent_id"):
        agent = roster.get(config["native_agent_id"], {})
        if agent.get("adapterType") != "process":
            raise BridgeError("NON_MODEL_COORDINATOR_REQUIRED")
        result["_coordinator"] = {"id": agent["id"], "company_id": config["company_id"],
                                  "project_id": config["project_id"], "adapter_type": "process",
                                  "observed_at": time.time()}
    return result


def resolve_recovery(config, context, backend):
    """Only a pinned successful receipt may repair this one disposition kind.

    backend is a separately provisioned narrow operator proxy or the owner API.
    Never pass a board credential to the bridge. Uncertain writes are quarantined.
    """
    issue = bound_issue(config, context, backend)
    journal = Journal(config["receipt_root"])
    with journal.connect() as c:
        row = c.execute("SELECT * FROM receipts WHERE task=?", (context["task_id"],)).fetchone()
    if not row or not row["record"]:
        raise BridgeError("VERIFIED_RECEIPT_REQUIRED")
    record = json.loads(row["record"])
    expected = {"task_id": context["task_id"], "issue_id": context["issue_id"],
                "agent_id": context["profile"], "run_id": row["run"]}
    if any(record["manifest"].get(key) != value for key, value in expected.items()):
        raise BridgeError("VERIFIED_RECEIPT_REQUIRED")
    tests = native_verify(config, record)
    if (tests.get("status") != "passed" or tests.get("manifest_digest") != record["digest"]
            or tests.get("credential_free") is not True or tests.get("network_policy") != "deny-all"
            or tests.get("seccomp") != config["test_seccomp_profile"]):
        raise BridgeError("VERIFIED_RECEIPT_REQUIRED")
    run = backend.run(row["run"])
    run_context = run.get("contextSnapshot") or {}
    if (run.get("id") != row["run"] or run.get("companyId") != config["company_id"]
            or run.get("agentId") != context["profile"]
            or (run_context.get("issueId") or run_context.get("taskId")) != context["issue_id"]
            or run.get("status") != "succeeded" or not run.get("finishedAt")
            or stamp(run["finishedAt"]) < stamp(run["createdAt"])
            or not cleanup(config, context["profile"], row["run"])):
        raise BridgeError("INVALID_TERMINAL_EVIDENCE")
    # Verification may take time; never use the issue-lock view from before tests.
    issue = bound_issue(config, context, backend)
    response = backend.request("GET", "/api/issues/" + backend.segment(context["issue_id"]) + "/recovery-actions")
    action = response.get("active")
    if not action:
        return {"state": "clear"}
    if (action.get("companyId") != config["company_id"] or action.get("sourceIssueId") != context["issue_id"]
            or action.get("kind") != "deliberate_wait_without_target"
            or action.get("cause") != "deliberate_wait_without_target"
            or action.get("ownerType") != "agent"
            or action.get("ownerAgentId") != context["profile"] or action.get("status") != "active"
            or not isinstance(action.get("evidence"), dict)
            or action.get("evidence", {}).get("latestRunId") != row["run"]
            or action.get("evidence", {}).get("latestRunStatus") != "succeeded"
            or issue.get("status") not in {"in_progress", "in_review"} or issue.get("executionRunId") or issue.get("checkoutRunId")):
        raise BridgeError("RECOVERY_SCOPE_MISMATCH")
    action_id = uuid_value(action["id"])
    with journal.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        previous = c.execute("SELECT recovery FROM receipts WHERE task=?", (context["task_id"],)).fetchone()[0]
        if previous:
            raise BridgeError("RECOVERY_WRITE_REQUIRES_RECONCILIATION")
        intent = {"action_id": action_id, "run_id": row["run"], "digest": record["digest"],
                  "outcome": "restored", "source_status": "in_review", "state": "intent", "at": time.time()}
        c.execute("UPDATE receipts SET recovery=? WHERE task=?", (canonical(intent), context["task_id"]))
    # No retry after HTTP403 or an uncertain result. On restart GET may show clear;
    # an active action after intent persistence requires operator reconciliation.
    backend.request("POST", "/api/issues/" + backend.segment(context["issue_id"]) + "/recovery-actions/resolve",
                    {"actionId": action_id, "outcome": "restored", "sourceIssueStatus": "in_review",
                     "resolutionNote": "Pinned native receipt; formal review path retained; no execution replay."})
    if backend.request("GET", "/api/issues/" + backend.segment(context["issue_id"]) + "/recovery-actions").get("active"):
        raise BridgeError("RECOVERY_NOT_CONFIRMED")
    confirmed = bound_issue(config, context, backend)
    if (confirmed.get("status") != "in_review" or confirmed.get("executionRunId")
            or confirmed.get("checkoutRunId")):
        raise BridgeError("RECOVERY_NOT_CONFIRMED")
    with journal.connect() as c:
        c.execute("UPDATE receipts SET recovery=? WHERE task=?",
                  (canonical({**intent, "state": "confirmed", "confirmed_at": time.time()}), context["task_id"]))
    return {"state": "resolved", "action_id": action_id}


def executor_handoff(config, backend, run_id):
    """Fixed helper called before the authorized executor exits. Own issue only."""
    run_id = uuid_value(run_id)
    run = backend.run(run_id)
    identity = config["executor_agent_id"]
    ctx = run.get("contextSnapshot") or {}
    issue_id = uuid_value(ctx.get("issueId") or ctx.get("taskId"))
    issue = backend.issue(issue_id)
    if (run.get("id") != run_id or run.get("status") != "running" or run.get("agentId") != identity
            or run.get("companyId") != config["company_id"] or issue.get("projectId") != config["project_id"]
            or issue.get("companyId") != config["company_id"]
            or issue.get("executionRunId") not in {None, run_id}
            or issue.get("checkoutRunId") not in {None, run_id}):
        raise BridgeError("EXECUTOR_CONTEXT_MISMATCH")
    if issue.get("assigneeAgentId") != identity or issue.get("status") not in {"in_progress", "in_review"}:
        raise BridgeError("EXECUTOR_CONTEXT_MISMATCH")
    from .native_review import handoff
    return handoff(config, backend, run, issue)


def native_verify(config, record):
    """Only trusted gateway config can select a remote verifier; never a request."""
    import hashlib
    if hashlib.sha256(canonical(record["manifest"]).encode()).hexdigest() != record["digest"]:
        raise BridgeError("MANIFEST_MISMATCH")
    if config.get("native_verify_command"):
        from .fixed_command import call
        tests = call(config["native_verify_command"], record, timeout=100, limit=2_000_000)
    else:
        from .gateway import verify
        tests = verify(config, record)
    if (not isinstance(tests, dict) or tests.get("manifest_digest") != record["digest"]
            or tests.get("status") not in {"passed", "failed"}
            or tests.get("credential_free") is not True or tests.get("network_policy") != "deny-all"
            or tests.get("seccomp") != config["test_seccomp_profile"]):
        raise BridgeError("INVALID_VERIFIER_RECEIPT")
    return tests


def repair_requested(context):
    """Any recovery-shaped wake must never fall through to a provider."""
    return any(key in context for key in ("recoveryActionId", "dispositionRepairSourceRunId",
                                          "retryOfRunId", "retryReason")) or "repair" in str(
                                              context.get("wakeReason", "")).lower() or "recovery" in str(
                                              context.get("wakeReason", "")).lower()


def validate_repair(config, backend, run, source, issue, *, active_only=True):
    """Authenticate native telemetry and the exact bounded disposition action."""
    ctx = run.get("contextSnapshot") or {}
    source_ctx = source.get("contextSnapshot") or {}
    source_id = ctx.get("dispositionRepairSourceRunId") or ctx.get("retryOfRunId")
    action_id = uuid_value(ctx.get("recoveryActionId"))
    issue_id = issue.get("id")
    if (ctx.get("wakeReason") != "issue_disposition_repair"
            or ctx.get("source") != "issue.deliberate_wait_disposition_repair"
            or (ctx.get("issueId") or ctx.get("taskId")) != issue_id
            or source_id != source.get("id") or run.get("id") == source_id
            or (ctx.get("retryOfRunId") and ctx["retryOfRunId"] != source_id)
            or run.get("companyId") != config["company_id"]
            or source.get("companyId") != config["company_id"]
            or source.get("agentId") != run.get("agentId")
            or issue.get("companyId") != config["company_id"]
            or issue.get("projectId") != config["project_id"]
            or (source_ctx.get("issueId") or source_ctx.get("taskId")) != issue_id
            or source.get("status") != "succeeded" or not source.get("finishedAt")
            or stamp(source["finishedAt"]) < stamp(source["createdAt"])
            or stamp(run["createdAt"]) < stamp(source["finishedAt"])):
        raise BridgeError("INVALID_DISPOSITION_REPAIR")
    response = backend.request("GET", "/api/issues/" + backend.segment(issue_id) + "/recovery-actions")
    action = response.get("active")
    if action and action.get("id") != action_id:
        raise BridgeError("INVALID_DISPOSITION_REPAIR")
    if not action:
        # Recovery GET exposes active actions only. A native repair card was
        # created by this exact server-authenticated repair run before parking;
        # its preserved action is corroborated by immutable server run context.
        from .native_review import binding, details, path, validate
        cards = backend.request("GET", path(backend, issue_id))
        matches = [r for r in cards if r.get("sourceRunId") == run.get("id")
                   and r.get("idempotencyKey") == "native-review:" + run["id"]]
        if len(matches) != 1:
            raise BridgeError("INVALID_DISPOSITION_REPAIR")
        saved = details(matches[0]).get("recovery_action")
        validate(matches[0], binding(run, issue, saved), allow_human=active_only)
        action = saved
    if (not isinstance(action, dict) or action.get("id") != action_id
            or action.get("companyId") != config["company_id"] or action.get("sourceIssueId") != issue_id
            or action.get("kind") != "deliberate_wait_without_target"
            or action.get("cause") != "deliberate_wait_without_target"
            or action.get("ownerType") != "agent" or action.get("ownerAgentId") != run.get("agentId")
            or action.get("status") != "active"
            or not isinstance(action.get("evidence"), dict)
            or action["evidence"].get("latestRunId") != source_id
            or action["evidence"].get("latestRunStatus") != "succeeded"):
        raise BridgeError("INVALID_DISPOSITION_REPAIR")
    if not active_only and (not run.get("finishedAt")
                           or stamp(run["finishedAt"]) < stamp(run["createdAt"])):
        raise BridgeError("INVALID_DISPOSITION_REPAIR")
    return action
