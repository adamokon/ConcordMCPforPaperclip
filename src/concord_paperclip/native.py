"""Run as the Process adapter of the dedicated non-model coordinator agent.

The platform supplies its real run id. Persistent task_bridge credentials keep
project/assignee limits. The native JWT authenticates the Process and reads only
bound run telemetry; it never authorizes a mutation. Native completion uses an
explicit operator-policy capability, never an invented native reviewer identity.
"""

import os

from .config import make_engine
from .policy import BridgeError
from .paperclip import Paperclip


def execute(config, run_id=None, runtime_token=None):
    run_id = run_id or os.environ.get("PAPERCLIP_RUN_ID")
    runtime_token = runtime_token or os.environ.get("PAPERCLIP_API_KEY")
    if not run_id or not runtime_token:
        raise BridgeError("NATIVE_CONTEXT_REQUIRED")
    engine = make_engine(config)
    engine.backend.run_id = run_id
    # Authenticate this exact native run and read bound telemetry with its JWT.
    # All writes use the narrower persistent task_bridge key and real run header.
    runtime = Paperclip(config["base_url"], config["company_id"], runtime_token, run_id=run_id,
                        trusted_http_hosts=config.get("trusted_http_hosts", []))
    run = runtime.run(run_id)
    if run.get("agentId") != config["native_agent_id"] or run.get("status") != "running":
        raise BridgeError("NATIVE_RUN_MISMATCH")
    if run.get("companyId") != config["company_id"] or run.get("id") != run_id:
        raise BridgeError("NATIVE_RUN_MISMATCH")
    from .wake import require_coordinator
    require_coordinator(runtime, config)
    context = run.get("contextSnapshot") or {}
    task_id = context.get("issueId") or context.get("taskId")
    if not task_id:
        raise BridgeError("NATIVE_CONTEXT_REQUIRED")
    own_issue = engine.backend.issue(task_id)
    if own_issue.get("assigneeAgentId") != config["native_agent_id"]:
        raise BridgeError("NATIVE_ASSIGNMENT_MISMATCH")
    for issue_id in config.get("cleanup_issues", []):
        old_issue = engine.backend.issue(issue_id)
        if (old_issue.get("projectId") != config["project_id"] or old_issue.get("executionRunId")
                or old_issue.get("checkoutRunId")):
            raise BridgeError("CLEANUP_SCOPE_MISMATCH")
        if old_issue.get("status") not in {"done", "cancelled"}:
            engine.backend.patch(issue_id, {"status": "cancelled"})
    engine.recover()
    if config.get("gateway_command"):
        from .automation import refresh_profiles
        refresh_profiles(engine, config)
    result = {"created": engine.drain(), "dispatches": []}
    with engine.store.connect() as c:
        tasks = [dict(r) for r in c.execute("SELECT id,version FROM tasks WHERE state='backlog'")]
    for task in tasks:
        try:
            dispatched = engine.dispatch(task["id"], task["version"])
            result["dispatches"].append({key: dispatched[key] for key in ("id", "issue_id", "state")})
        except BridgeError as e:
            result["dispatches"].append({"id": task["id"], "code": e.code})
    # Selection is explicit, before any accept attempt; never an HTTP-error fallback.
    engine.native_completion_config = config
    engine.native_coordinator_id = config["native_agent_id"]
    engine.native_read_backend = runtime
    engine.close_reviews()
    # This is the real current run operating on its own control issue.
    engine.backend.patch(own_issue["id"], {"status": "done"})
    return {"status": "success", "created_count": len(result["created"]),
            "dispatch_count": len(result["dispatches"]), "dispatch_results": result["dispatches"]}
