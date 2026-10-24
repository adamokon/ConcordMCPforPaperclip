"""Executor handoff and explicitly configured operator-policy completion review."""

import json
import re

from .policy import BridgeError
from .store import canonical

KEY = "native_completion_review"
PROMPT = "Approve native bridge completion after independent artifact verification?"


def path(backend, issue_id):
    return "/api/issues/" + backend.segment(issue_id) + "/interactions"


def binding(run, issue, action=None):
    from .codex_receipt import uuid_value
    match = re.search(r"(?m)^Bridge reference: ([0-9a-f-]{36})$", issue.get("description") or "")
    if not match:
        raise BridgeError("FORMAL_HANDOFF_REQUIRED")
    ctx = run.get("contextSnapshot") or {}
    if action is not None:
        action = {k: action.get(k) for k in ("id", "companyId", "sourceIssueId", "kind", "cause",
                                             "ownerType", "ownerAgentId", "status") } | {
            "evidence": {k: (action.get("evidence") or {}).get(k)
                         for k in ("latestRunId", "latestRunStatus")}}
    return dict(version=1, task_id=uuid_value(match[1]), issue_id=uuid_value(issue["id"]),
                company_id=uuid_value(issue["companyId"]), project_id=uuid_value(issue["projectId"]),
                executor_id=uuid_value(run["agentId"]), handoff_run_id=uuid_value(run["id"]),
                source_run_id=uuid_value(ctx.get("dispositionRepairSourceRunId") or ctx.get("retryOfRunId") or run["id"]),
                recovery_action=action)


def details(row):
    try:
        result = json.loads(row["payload"]["detailsMarkdown"])
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (KeyError, TypeError, ValueError):
        raise BridgeError("INVALID_NATIVE_REVIEW") from None


def validate(row, expected, *, allow_human=False):
    payload = row.get("payload") or {}
    fields = {"version", "task_id", "issue_id", "company_id", "project_id", "executor_id",
              "handoff_run_id", "source_run_id", "recovery_action"}
    if set(expected) != fields or expected.get("version") != 1:
        raise BridgeError("INVALID_NATIVE_REVIEW")
    from .codex_receipt import uuid_value
    for key in fields - {"version", "recovery_action"}:
        uuid_value(expected[key])
    if (row.get("companyId") != expected["company_id"] or row.get("issueId") != expected["issue_id"]
            or row.get("kind") != "request_confirmation" or row.get("continuationPolicy") != "none"
            or row.get("createdByAgentId") != expected["executor_id"]
            or row.get("sourceRunId") != expected["handoff_run_id"]
            or row.get("addresseeAgentId") or row.get("addresseeUserId")
            or row.get("idempotencyKey") != "native-review:" + expected["handoff_run_id"]
            or (not allow_human and row.get("effectiveResolverPolicy") != "anyone")
            or row.get("status") not in {"pending", "accepted"}
            or payload.get("toolAction") is not None or payload.get("secretProposal") is not None
            or payload.get("supersedeOnUserComment") is not False
            or payload.get("prompt") != PROMPT
            or payload.get("target") != {"type": "custom", "key": KEY,
                                         "revisionId": expected["source_run_id"]}
            or details(row) != expected):
        raise BridgeError("INVALID_NATIVE_REVIEW")
    return row


def handoff(config, backend, run, issue):
    from .codex_receipt import Journal, repair_requested, validate_repair
    action = None
    if repair_requested(run.get("contextSnapshot") or {}):
        source = backend.run(run["contextSnapshot"].get("dispositionRepairSourceRunId")
                             or run["contextSnapshot"].get("retryOfRunId"))
        # A second helper call may follow automatic source revalidation. Validate
        # the previously created exact card using server-bound native run context.
        action = validate_repair(config, backend, run, source, issue)
    expected = binding(run, issue, action)
    endpoint = path(backend, issue["id"])
    key = "native-review:" + run["id"]
    rows = backend.request("GET", endpoint)
    matches = [r for r in rows if r.get("idempotencyKey") == key]
    if len(matches) > 1:
        raise BridgeError("INVALID_NATIVE_REVIEW")
    journal = Journal(config["handoff_root"])
    with journal.connect() as c:
        c.execute("CREATE TABLE IF NOT EXISTS handoffs (key TEXT PRIMARY KEY, binding TEXT NOT NULL)")
    if matches:
        card = validate(matches[0], expected, allow_human=True)
        if card["status"] != "pending":
            raise BridgeError("INVALID_NATIVE_REVIEW")
    else:
        with journal.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            if c.execute("SELECT 1 FROM handoffs WHERE key=?", (key,)).fetchone():
                raise BridgeError("HANDOFF_WRITE_REQUIRES_RECONCILIATION")
            c.execute("INSERT INTO handoffs VALUES(?,?)", (key, canonical(expected)))
        # Do not address the Process agent: the route wakes addressed agents on
        # this executor issue. Its later wake must use a separate control issue.
        backend.request("POST", endpoint, {
            "kind": "request_confirmation", "idempotencyKey": key, "resolverPolicy": "anyone",
            "continuationPolicy": "none", "title": "Bridge completion: operator-policy review",
            "payload": {"version": 1, "prompt": PROMPT, "supersedeOnUserComment": False,
                        "detailsMarkdown": canonical(expected),
                        "target": {"type": "custom", "key": KEY, "revisionId": expected["source_run_id"]}},
        })
        rows = backend.request("GET", endpoint)
        matches = [r for r in rows if r.get("idempotencyKey") == key]
        if len(matches) != 1:
            raise BridgeError("HANDOFF_NOT_CONFIRMED")
        validate(matches[0], expected, allow_human=True)
    issue = backend.issue(issue["id"])
    if (issue.get("companyId") != expected["company_id"] or issue.get("projectId") != expected["project_id"]
            or issue.get("assigneeAgentId") != expected["executor_id"]
            or issue.get("status") not in {"in_progress", "in_review"}
            or issue.get("executionRunId") not in {None, run["id"]}
            or issue.get("checkoutRunId") not in {None, run["id"]}):
        raise BridgeError("EXECUTOR_CONTEXT_MISMATCH")
    if issue["status"] != "in_review":
        # Journal the status write separately. Uncertain writes reconcile only by
        # readback; an absent effect never triggers a blind retry.
        park_key = key + ":park"
        with journal.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            if c.execute("SELECT 1 FROM handoffs WHERE key=?", (park_key,)).fetchone():
                raise BridgeError("HANDOFF_WRITE_REQUIRES_RECONCILIATION")
            c.execute("INSERT INTO handoffs VALUES(?,?)", (park_key, canonical(expected)))
        backend.patch(issue["id"], {"status": "in_review"})
    confirmed = backend.issue(issue["id"])
    if confirmed.get("status") != "in_review" or confirmed.get("assigneeAgentId") != run["agentId"]:
        raise BridgeError("HANDOFF_NOT_CONFIRMED")
    return {"state": "in_review", "interaction_id": matches[0]["id"]}


def accept(engine, task, manifest):
    """Real Process authorizes a bounded operator hook; it is never the resolver."""
    from .codex_receipt import stamp
    from . import operator_review
    policy = operator_review.configuration(getattr(engine, "native_completion_config", {}))
    backend = engine.backend
    # task_bridge cannot read company run telemetry. This read-only client exists
    # only inside the already authenticated Process. Normal mutations stay scoped;
    # completion alone uses the explicitly provisioned operator capability.
    telemetry = getattr(engine, "native_read_backend", backend)
    digest = engine.artifacts(task["id"])["digest"]
    with engine.store.connect() as c:
        approvals = [dict(r) for r in c.execute(
            "SELECT owner,key,payload FROM operations WHERE task_id=? AND kind='review' ORDER BY key",
            (task["id"],))]
        for approval in approvals:
            approval["payload"] = json.loads(approval["payload"])
        tests = [json.loads(r[0]) for r in c.execute(
            "SELECT details FROM audit WHERE task_id=? AND event='independent_tests' ORDER BY id", (task["id"],))]
    if not any(a["payload"].get("digest") == digest for a in approvals) or not any(
            t.get("manifest_digest") == digest and t.get("status") == "passed"
            and t.get("credential_free") is True and t.get("network_policy") == "deny-all"
            and t.get("seccomp") == engine.native_completion_config.get("verifier_seccomp_profile")
            and isinstance(t.get("seccomp"), str) and t["seccomp"] for t in tests):
        raise BridgeError("VERIFIED_REVIEW_REQUIRED")
    remote = backend.issue(task["issue_id"])
    rows = backend.request("GET", path(backend, task["issue_id"]))
    candidates = []
    for row in rows:
        if ((row.get("payload") or {}).get("target") or {}).get("key") != KEY:
            continue
        expected = details(row)
        if expected.get("source_run_id") != manifest["run_id"]:
            continue
        required = dict(task_id=task["id"], issue_id=task["issue_id"], company_id=remote["companyId"],
                        project_id=remote["projectId"], executor_id=manifest["agent_id"])
        if any(expected.get(k) != v for k, v in required.items()):
            raise BridgeError("INVALID_NATIVE_REVIEW")
        validate(row, expected)
        if remote.get("assigneeAgentId") != manifest["agent_id"]:
            raise BridgeError("INVALID_NATIVE_REVIEW")
        source = telemetry.run(row["sourceRunId"])
        ctx = source.get("contextSnapshot") or {}
        if (source.get("id") != row["sourceRunId"] or source.get("agentId") != manifest["agent_id"]
                or source.get("companyId") != remote["companyId"] or source.get("status") != "succeeded"
                or (ctx.get("issueId") or ctx.get("taskId")) != task["issue_id"]
                or not source.get("finishedAt") or stamp(source["finishedAt"]) < stamp(source["createdAt"])
                or stamp(row.get("createdAt")) < stamp(source["createdAt"])
                or stamp(row.get("createdAt")) > stamp(source["finishedAt"])):
            raise BridgeError("INVALID_NATIVE_REVIEW")
        if source["id"] != manifest["run_id"]:
            from .codex_receipt import validate_repair
            original = telemetry.run(manifest["run_id"])
            validate_repair({"company_id": remote["companyId"], "project_id": remote["projectId"]},
                            backend, source, original, remote, active_only=False)
        candidates.append(row)
    if len(candidates) != 1 or any(r.get("status") == "pending" and r["id"] != candidates[0]["id"] for r in rows):
        raise BridgeError("FORMAL_HANDOFF_REQUIRED")
    row = candidates[0]
    # The request is stable across coordinator restarts. Resolution fields are
    # excluded so GET-only reconciliation hashes the same originally pending card.
    pending = {k: row.get(k) for k in (
        "id", "companyId", "issueId", "kind", "createdAt", "createdByAgentId", "sourceRunId",
        "idempotencyKey", "continuationPolicy", "effectiveResolverPolicy", "payload")}
    with engine.store.connect() as c:
        submission = c.execute("SELECT owner,key FROM operations WHERE task_id=? AND kind='submit'",
                               (task["id"],)).fetchone()
    if not submission:
        raise BridgeError("VERIFIED_REVIEW_REQUIRED")
    submit_binding = {**dict(submission), "spec_digest": operator_review.digest(json.loads(task["spec"]))}
    value = operator_review.request(policy, task, pending, manifest, submit_binding,
                                    [t for t in tests if t.get("manifest_digest") == digest],
                                    [a for a in approvals if a["payload"].get("digest") == digest])
    request_digest = operator_review.digest(value)
    event = "native_accept_intent"
    with engine.store.transaction() as c:
        intents = [json.loads(r[0]) for r in c.execute(
            "SELECT details FROM audit WHERE task_id=? AND event=? ORDER BY id", (task["id"], event))]
        if intents:
            # Includes legacy agent409 intents: no automatic migration or replay.
            if len(intents) != 1 or intents[0].get("request_sha256") != request_digest:
                raise BridgeError("ACCEPT_WRITE_REQUIRES_RECONCILIATION")
            if row["status"] == "pending":
                raise BridgeError("ACCEPT_WRITE_REQUIRES_RECONCILIATION")
        elif row["status"] != "pending":
            raise BridgeError("ACCEPT_WITHOUT_INTENT")
        else:
            engine.store.audit(c, "operator-policy", task["id"], event,
                               {"interaction_id": row["id"], "digest": digest,
                                "request_sha256": request_digest, "contract": policy["contract"],
                                "policy_id": policy["policy_id"], "user_id": policy["user_id"]})
    if row["status"] == "pending":
        result = operator_review.invoke(policy, value)
        with engine.store.transaction() as c:
            engine.store.audit(c, "operator-policy", task["id"], "operator_accept_receipt", result)
        rows = backend.request("GET", path(backend, task["issue_id"]))
        row = next((r for r in rows if r["id"] == row["id"]), {})
        validate(row, expected=details(candidates[0]))
    operator_review.confirmed(row, policy)
