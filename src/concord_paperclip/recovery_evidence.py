"""
Authenticated pre-provider evidence decoder for automated recovery.
ConcordMCPforPaperclip trusted-host decoder for native telemetry.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Dict, Optional

_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z"
)
_HEX64_PATTERN = re.compile(r"^[0-9a-f]{64}\Z")

_ALLOWED_ISSUE_STATUSES = {
    "todo",
    "in_progress",
    "in_review",
    "blocked",
    "done",
    "cancelled",
}

_TERMINAL_ISSUE_STATUSES = {
    "done",
    "cancelled",
}

_ALLOWED_AGENT_STATUSES = {
    "idle",
    "active",
    "running",
    "paused",
    "terminated",
    "error",
}

_ALLOWED_RUN_STATUSES = {
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
    "error",
}

_ALLOWED_SUCCESSOR_STATUSES = {
    "queued",
    "running",
    "succeeded",
}

_STDOUT_REQUIRED_KEYS = {
    "kind",
    "task_id",
    "issue_id",
    "agent_id",
    "company_id",
    "project_id",
    "run_id",
    "producer_sha256",
    "error_kind",
}


class RecoveryEvidenceError(Exception):
    """Exception raised for malformed or scope-unsafe input during evidence derivation."""

    def __init__(self, message: str, code: str = "malformed_input") -> None:
        super().__init__(message)
        self.code = code


def _is_canonical_uuid(val: Any) -> bool:
    if not isinstance(val, str):
        return False
    return bool(_UUID_PATTERN.match(val))


def _is_lowerhex64(val: Any) -> bool:
    if not isinstance(val, str):
        return False
    return bool(_HEX64_PATTERN.match(val))


def _is_strict_bool(val: Any) -> bool:
    return type(val) is bool


def _is_strict_int(val: Any) -> bool:
    return type(val) is int


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except (ValueError, OverflowError):
        return False


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate attestation key")
        result[key] = value
    return result


def derive_evidence(
    expected: Any,
    native: Any,
    worker: Any,
    producer: Any,
    now: Any,
) -> Dict[str, Any]:
    """Derive authenticated evidence from native platform telemetry and root producer facts.

    Args:
        expected: Dict containing canonical UUIDs (task_id, issue_id, agent_id,
            source_run_id, attempt_id, company_id, project_id), repo string,
            and retries_used integer.
        native: Dict containing issue, agent, run, recovery_action_id,
            successors, and other_active_runs.
        worker: Dict containing environment_removed (strict bool) and
            workspace_absent (strict bool).
        producer: Dict containing expected_command (str), expected_sha256 (lowerhex64),
            actual_sha256 (lowerhex64), and exit_code (fixed 75).
        now: Finite numeric timestamp (float/int, not bool).

    Returns:
        Dict adhering to the full evidence schema consumed by the recovery policy.

    Raises:
        RecoveryEvidenceError: If inputs are malformed or violate scope/identity constraints.
    """
    # 1. Validate 'now'
    if not _finite(now):
        raise RecoveryEvidenceError(
            "Parameter 'now' must be a finite numeric value (not bool)",
            code="malformed_input",
        )

    # 2. Validate 'expected'
    if not isinstance(expected, dict):
        raise RecoveryEvidenceError("Parameter 'expected' must be a dict", code="malformed_input")

    expected_uuid_fields = (
        "task_id",
        "issue_id",
        "agent_id",
        "source_run_id",
        "attempt_id",
        "company_id",
        "project_id",
    )
    for field in expected_uuid_fields:
        val = expected.get(field)
        if not _is_canonical_uuid(val):
            raise RecoveryEvidenceError(
                f"Field '{field}' in expected must be a canonical UUID",
                code="malformed_input",
            )

    repo = expected.get("repo")
    if not isinstance(repo, str) or len(repo) == 0:
        raise RecoveryEvidenceError(
            "Field 'repo' in expected must be a non-empty string",
            code="malformed_input",
        )

    retries_used = expected.get("retries_used")
    if not _is_strict_int(retries_used) or retries_used < 0:
        raise RecoveryEvidenceError(
            "Field 'retries_used' in expected must be a non-negative integer",
            code="malformed_input",
        )

    # 3. Validate 'producer'
    if not isinstance(producer, dict):
        raise RecoveryEvidenceError("Parameter 'producer' must be a dict", code="malformed_input")

    expected_command = producer.get("expected_command")
    if not isinstance(expected_command, str) or len(expected_command) == 0:
        raise RecoveryEvidenceError(
            "Field 'expected_command' in producer must be a non-empty string",
            code="malformed_input",
        )

    expected_sha256 = producer.get("expected_sha256")
    if not _is_lowerhex64(expected_sha256):
        raise RecoveryEvidenceError(
            "Field 'expected_sha256' in producer must be a lowerhex64 string",
            code="malformed_input",
        )

    actual_sha256 = producer.get("actual_sha256")
    if not _is_lowerhex64(actual_sha256):
        raise RecoveryEvidenceError(
            "Field 'actual_sha256' in producer must be a lowerhex64 string",
            code="malformed_input",
        )

    prod_exit_code = producer.get("exit_code")
    if not _is_strict_int(prod_exit_code) or prod_exit_code != 75:
        raise RecoveryEvidenceError(
            "Field 'exit_code' in producer must be fixed integer 75",
            code="malformed_input",
        )

    # 4. Validate 'worker'
    if not isinstance(worker, dict):
        raise RecoveryEvidenceError("Parameter 'worker' must be a dict", code="malformed_input")

    env_removed = worker.get("environment_removed")
    if not _is_strict_bool(env_removed):
        raise RecoveryEvidenceError(
            "Field 'environment_removed' in worker must be a strict bool",
            code="malformed_input",
        )

    ws_absent = worker.get("workspace_absent")
    if not _is_strict_bool(ws_absent):
        raise RecoveryEvidenceError(
            "Field 'workspace_absent' in worker must be a strict bool",
            code="malformed_input",
        )

    # 5. Validate 'native'
    if not isinstance(native, dict):
        raise RecoveryEvidenceError("Parameter 'native' must be a dict", code="malformed_input")

    rec_action_id = native.get("recovery_action_id")
    if rec_action_id is not None and not _is_canonical_uuid(rec_action_id):
        raise RecoveryEvidenceError(
            "Field 'recovery_action_id' in native must be a canonical UUID or None",
            code="malformed_input",
        )

    # Validate native issue
    issue = native.get("issue")
    if not isinstance(issue, dict):
        raise RecoveryEvidenceError("Field 'issue' in native must be a dict", code="malformed_input")

    for req_key in (
        "id",
        "companyId",
        "projectId",
        "assigneeAgentId",
        "status",
        "executionRunId",
        "checkoutRunId",
    ):
        if req_key not in issue:
            raise RecoveryEvidenceError(
                f"Missing '{req_key}' in native issue",
                code="malformed_input",
            )

    if issue["id"] != expected["issue_id"]:
        raise RecoveryEvidenceError(
            "Native issue.id does not match expected issue_id",
            code="scope_violation",
        )
    if issue["companyId"] != expected["company_id"]:
        raise RecoveryEvidenceError(
            "Native issue.companyId does not match expected company_id",
            code="scope_violation",
        )
    if issue["projectId"] != expected["project_id"]:
        raise RecoveryEvidenceError(
            "Native issue.projectId does not match expected project_id",
            code="scope_violation",
        )
    if issue["assigneeAgentId"] != expected["agent_id"]:
        raise RecoveryEvidenceError(
            "Native issue.assigneeAgentId does not match expected agent_id",
            code="scope_violation",
        )

    exec_run_id = issue["executionRunId"]
    if exec_run_id is not None and not _is_canonical_uuid(exec_run_id):
        raise RecoveryEvidenceError(
            "Native issue.executionRunId must be canonical UUID or None",
            code="malformed_input",
        )

    checkout_run_id = issue["checkoutRunId"]
    if checkout_run_id is not None and not _is_canonical_uuid(checkout_run_id):
        raise RecoveryEvidenceError(
            "Native issue.checkoutRunId must be canonical UUID or None",
            code="malformed_input",
        )

    issue_status = issue["status"]
    if not isinstance(issue_status, str) or issue_status not in _ALLOWED_ISSUE_STATUSES:
        raise RecoveryEvidenceError(
            f"Invalid native issue status: {issue_status}",
            code="invalid_enum",
        )

    # Validate native agent
    agent = native.get("agent")
    if not isinstance(agent, dict):
        raise RecoveryEvidenceError("Field 'agent' in native must be a dict", code="malformed_input")

    for req_key in ("id", "status", "pauseReason", "adapterType", "command"):
        if req_key not in agent:
            raise RecoveryEvidenceError(
                f"Missing '{req_key}' in native agent",
                code="malformed_input",
            )

    if agent["id"] != expected["agent_id"]:
        raise RecoveryEvidenceError(
            "Native agent.id does not match expected agent_id",
            code="scope_violation",
        )

    agent_status = agent["status"]
    if not isinstance(agent_status, str) or agent_status not in _ALLOWED_AGENT_STATUSES:
        raise RecoveryEvidenceError(
            f"Invalid native agent status: {agent_status}",
            code="invalid_enum",
        )

    pause_reason = agent["pauseReason"]
    if pause_reason is not None and not isinstance(pause_reason, str):
        raise RecoveryEvidenceError(
            "Native agent.pauseReason must be string or None",
            code="malformed_input",
        )

    if not isinstance(agent["adapterType"], str):
        raise RecoveryEvidenceError(
            "Native agent.adapterType must be a string",
            code="malformed_input",
        )

    if not isinstance(agent["command"], str):
        raise RecoveryEvidenceError(
            "Native agent.command must be a string",
            code="malformed_input",
        )

    # Validate native run
    run = native.get("run")
    if not isinstance(run, dict):
        raise RecoveryEvidenceError("Field 'run' in native must be a dict", code="malformed_input")

    for req_key in ("id", "companyId", "agentId", "status", "exitCode", "resultJson"):
        if req_key not in run:
            raise RecoveryEvidenceError(
                f"Missing '{req_key}' in native run",
                code="malformed_input",
            )

    if run["id"] != expected["source_run_id"]:
        raise RecoveryEvidenceError(
            "Native run.id does not match expected source_run_id",
            code="scope_violation",
        )
    if run["companyId"] != expected["company_id"]:
        raise RecoveryEvidenceError(
            "Native run.companyId does not match expected company_id",
            code="scope_violation",
        )
    if run["agentId"] != expected["agent_id"]:
        raise RecoveryEvidenceError(
            "Native run.agentId does not match expected agent_id",
            code="scope_violation",
        )

    run_status = run["status"]
    if not isinstance(run_status, str) or run_status not in _ALLOWED_RUN_STATUSES:
        raise RecoveryEvidenceError(
            f"Invalid native run status: {run_status}",
            code="invalid_enum",
        )

    run_exit_code = run["exitCode"]
    if not isinstance(run["resultJson"], dict):
        raise RecoveryEvidenceError(
            "Native run.resultJson must be a dict",
            code="malformed_input",
        )

    # Validate native successors
    successors = native.get("successors")
    if not isinstance(successors, list):
        raise RecoveryEvidenceError(
            "Field 'successors' in native must be a list",
            code="malformed_input",
        )

    for succ in successors:
        if not isinstance(succ, dict):
            raise RecoveryEvidenceError("Successor entry must be a dict", code="malformed_input")
        for req_key in ("id", "companyId", "agentId", "status", "contextSnapshot"):
            if req_key not in succ:
                raise RecoveryEvidenceError(
                    f"Missing '{req_key}' in successor entry",
                    code="malformed_input",
                )
        if not _is_canonical_uuid(succ["id"]):
            raise RecoveryEvidenceError(
                "Successor id must be a canonical UUID",
                code="malformed_input",
            )
        if not _is_canonical_uuid(succ["companyId"]):
            raise RecoveryEvidenceError(
                "Successor companyId must be a canonical UUID",
                code="malformed_input",
            )
        if not _is_canonical_uuid(succ["agentId"]):
            raise RecoveryEvidenceError(
                "Successor agentId must be a canonical UUID",
                code="malformed_input",
            )
        if not isinstance(succ["status"], str):
            raise RecoveryEvidenceError(
                "Successor status must be a string",
                code="malformed_input",
            )
        cs = succ["contextSnapshot"]
        if not isinstance(cs, dict):
            raise RecoveryEvidenceError(
                "Successor contextSnapshot must be a dict",
                code="malformed_input",
            )
        if "issueId" not in cs or "recoveryActionId" not in cs:
            raise RecoveryEvidenceError(
                "Successor contextSnapshot must contain issueId and recoveryActionId",
                code="malformed_input",
            )
        if not _is_canonical_uuid(cs["issueId"]):
            raise RecoveryEvidenceError(
                "Successor contextSnapshot.issueId must be a canonical UUID",
                code="malformed_input",
            )
        if cs["recoveryActionId"] is not None and not _is_canonical_uuid(cs["recoveryActionId"]):
            raise RecoveryEvidenceError(
                "Successor contextSnapshot.recoveryActionId must be canonical UUID or None",
                code="malformed_input",
            )

    # Validate other_active_runs
    other_active_runs = native.get("other_active_runs")
    if not isinstance(other_active_runs, list):
        raise RecoveryEvidenceError(
            "Field 'other_active_runs' in native must be a list",
            code="malformed_input",
        )

    for oar in other_active_runs:
        if not isinstance(oar, dict) or "id" not in oar:
            raise RecoveryEvidenceError(
                "other_active_runs entries must be dicts with 'id'",
                code="malformed_input",
            )
        if not _is_canonical_uuid(oar["id"]):
            raise RecoveryEvidenceError(
                "other_active_runs entry id must be a canonical UUID",
                code="malformed_input",
            )

    # 6. Successor Adoption Logic
    new_run: Optional[Dict[str, Any]] = None
    if rec_action_id is not None:
        matching_candidates = []
        for succ in successors:
            cs = succ["contextSnapshot"]
            if cs.get("recoveryActionId") == rec_action_id:
                matching_candidates.append(succ)

        if len(matching_candidates) > 1:
            raise RecoveryEvidenceError(
                f"Ambiguous successors: found {len(matching_candidates)} candidates matching recovery_action_id",
                code="ambiguous_successor",
            )

        if len(matching_candidates) == 1:
            cand = matching_candidates[0]
            if cand["id"] == expected["source_run_id"]:
                raise RecoveryEvidenceError(
                    "Successor reuses source_run_id",
                    code="scope_violation",
                )
            if cand["companyId"] != expected["company_id"]:
                raise RecoveryEvidenceError(
                    "Successor companyId mismatch",
                    code="scope_violation",
                )
            if cand["agentId"] != expected["agent_id"]:
                raise RecoveryEvidenceError(
                    "Successor agentId mismatch",
                    code="scope_violation",
                )
            if cand["contextSnapshot"]["issueId"] != expected["issue_id"]:
                raise RecoveryEvidenceError(
                    "Successor contextSnapshot.issueId mismatch",
                    code="scope_violation",
                )
            if cand["status"] not in _ALLOWED_SUCCESSOR_STATUSES:
                raise RecoveryEvidenceError(
                    f"Successor status '{cand['status']}' not in allowed statuses ({_ALLOWED_SUCCESSOR_STATUSES})",
                    code="invalid_status",
                )

            new_run = {
                "id": cand["id"],
                "status": cand["status"],
                "task_id": expected["task_id"],
                "issue_id": expected["issue_id"],
                "agent_id": expected["agent_id"],
                "company_id": expected["company_id"],
                "project_id": expected["project_id"],
                "source_run_id": expected["source_run_id"],
                "recovery_action_id": rec_action_id,
            }

    # 7. Other Run Active Evaluation
    adopted_id = new_run["id"] if new_run is not None else None
    other_run_active = False
    for oar in other_active_runs:
        if adopted_id is not None and oar["id"] == adopted_id:
            continue
        other_run_active = True
        break

    if any(lock is not None and lock != adopted_id for lock in (exec_run_id, checkout_run_id)):
        other_run_active = True

    # 8. Agent Paused / Terminated Strict Bools
    is_paused = (agent_status == "paused") or bool(pause_reason and pause_reason.strip())
    is_terminated = (agent_status == "terminated")

    # 9. Attestation and No-Effects Proof
    if issue_status in _TERMINAL_ISSUE_STATUSES:
        provider_started = None
        effects = "unknown"
        attestation = None
        error_kind = "security"
    elif run_status == "succeeded":
        provider_started = True
        effects = "completed"
        attestation = "trusted_worker_result_v1"
        error_kind = None
    else:
        proof_valid = False
        if run_status == "failed":
            # Native exitCode must be strictly integer 75 (reject bool, float, etc.)
            if _is_strict_int(run_exit_code) and run_exit_code == 75:
                if env_removed is True and ws_absent is True:
                    if agent.get("adapterType") == "process":
                        if agent.get("command") == expected_command:
                            if expected_sha256 == actual_sha256:
                                stdout_raw = run["resultJson"].get("stdout")
                                if isinstance(stdout_raw, str):
                                    try:
                                        stdout_bytes = stdout_raw.encode("utf-8")
                                        if len(stdout_bytes) <= 4096:
                                            payload = json.loads(stdout_raw, object_pairs_hook=_unique_object)
                                            if isinstance(payload, dict):
                                                if set(payload.keys()) == _STDOUT_REQUIRED_KEYS:
                                                    if (
                                                        payload["kind"]
                                                        == "concord.pre_provider_failure.v1"
                                                        and payload["task_id"]
                                                        == expected["task_id"]
                                                        and payload["issue_id"]
                                                        == expected["issue_id"]
                                                        and payload["agent_id"]
                                                        == expected["agent_id"]
                                                        and payload["company_id"]
                                                        == expected["company_id"]
                                                        and payload["project_id"]
                                                        == expected["project_id"]
                                                        and payload["run_id"]
                                                        == expected["source_run_id"]
                                                        and payload["producer_sha256"]
                                                        == expected_sha256
                                                        and payload["error_kind"]
                                                        == "pre_provider_transient"
                                                    ):
                                                        proof_valid = True
                                    except Exception:
                                        pass

        if proof_valid:
            provider_started = False
            effects = "not_performed"
            attestation = "trusted_pre_provider_v1"
            error_kind = "pre_provider_transient"
        else:
            provider_started = None
            effects = "unknown"
            attestation = None
            error_kind = "unknown"

    return {
        "task_id": expected["task_id"],
        "issue_id": expected["issue_id"],
        "agent_id": expected["agent_id"],
        "source_run_id": expected["source_run_id"],
        "attempt_id": expected["attempt_id"],
        "company_id": expected["company_id"],
        "project_id": expected["project_id"],
        "observed_at": now,
        "native_status": run_status,
        "cleanup_complete": env_removed,
        "other_run_active": other_run_active,
        "provider_started": provider_started,
        "effects": effects,
        "attestation": attestation,
        "error_kind": error_kind,
        "paused": is_paused,
        "terminated": is_terminated,
        "recovery_action_id": rec_action_id,
        "new_run": new_run,
    }
