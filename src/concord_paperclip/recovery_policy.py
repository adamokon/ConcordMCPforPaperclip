"""
recovery_policy.py - Pure fail-closed same-issue recovery decision policy.

Part of ConcordMCPforPaperclip (Independent Python MCP/Paperclip bridge).

Design & Malformed-Input Policy:
- Fail-Closed: Any contract violation, non-canonical UUID, type masquerading
  (e.g., bool as int/float), non-finite clock, missing field, or out-of-scope
  attribute causes the policy to immediately reject/block recovery.
- By default, decide_recovery() returns a decision dict `{"action": "block", "code": "<code_name>"}`.
- For callers requiring exception-based error reporting, RecoveryPolicyError
  is exported and can be raised by passing `raise_on_error=True`.
- Policy is a root-owned preauthorization; it is never accepted from MCP task text.
- Evidence is sourced solely from a trusted fixed gateway, never worker messages.
"""

import math
import re
from typing import Any, Dict, Union
import uuid

__all__ = [
    "RecoveryPolicyError",
    "decide_recovery",
    "is_canonical_uuid",
]

CANONICAL_UUID_REGEX = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

IDENTITY_FIELDS = (
    "task_id",
    "issue_id",
    "agent_id",
    "source_run_id",
    "attempt_id",
    "company_id",
    "project_id",
)

VALID_NATIVE_STATUSES = {
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "timed_out",
    "unknown",
}

VALID_EFFECTS = {
    "not_performed",
    "completed",
    "unknown",
}

VALID_ATTESTATIONS = {
    "trusted_pre_provider_v1",
    "trusted_worker_result_v1",
    None,
}

VALID_ERROR_KINDS = {
    "pre_provider_transient",
    "auth",
    "quota",
    "security",
    "provider_failure",
    "unknown",
    None,
}

VALID_BIND_STATUSES = {
    "queued",
    "running",
    "succeeded",
}


class RecoveryPolicyError(ValueError):
    """Raised when recovery policy validation fails in strict mode or input is malformed."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code


def is_canonical_uuid(val: Any) -> bool:
    """Return True if val is strictly a canonical lowercase UUID string."""
    if not isinstance(val, str):
        return False
    if not CANONICAL_UUID_REGEX.match(val):
        return False
    try:
        u = uuid.UUID(val)
        return str(u) == val
    except (ValueError, AttributeError):
        return False


def is_strict_bool(val: Any) -> bool:
    """Return True if val is strictly a bool (not int or numeric masquerading as bool)."""
    return isinstance(val, bool)


def is_strict_int(val: Any) -> bool:
    """Return True if val is strictly an int (rejects bools masquerading as ints)."""
    return isinstance(val, int) and not isinstance(val, bool)


def is_strict_finite_number(val: Any) -> bool:
    """Return True if val is a finite number (int or float, rejects bools and inf/nan)."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    try:
        return math.isfinite(val)
    except (OverflowError, ValueError):
        return False


def _member(value, choices):
    return (value is None or isinstance(value, str)) and value in choices


def _fail(code: str, message: str, raise_on_error: bool) -> Dict[str, str]:
    if raise_on_error:
        raise RecoveryPolicyError(code, message)
    return {"action": "block", "code": code}


def decide_recovery(
    policy: Dict[str, Any],
    expected: Dict[str, Any],
    evidence: Dict[str, Any],
    now: Union[float, int],
    *,
    raise_on_error: bool = False,
) -> Dict[str, str]:
    """
    Pure decision function for bounded, proven-safe same-issue recovery.

    Args:
        policy: Root-owned preauthorization configuration.
        expected: Expected binding facts (7 UUIDs, repo, retries_used).
        evidence: Trusted gateway facts.
        now: Current timestamp (finite numeric).
        raise_on_error: If True, raises RecoveryPolicyError on contract / malformed inputs
                        instead of returning a block decision.

    Returns:
        Dict with "action" in {"block", "wait", "receive", "retry", "bind"} and "code".
    """
    # -------------------------------------------------------------------------
    # 1. Structural / Type Validation
    # -------------------------------------------------------------------------
    if not isinstance(policy, dict):
        return _fail("malformed_policy", "policy must be a dict", raise_on_error)
    if not isinstance(expected, dict):
        return _fail("malformed_expected", "expected must be a dict", raise_on_error)
    if not isinstance(evidence, dict):
        return _fail("malformed_evidence", "evidence must be a dict", raise_on_error)
    if not is_strict_finite_number(now):
        return _fail("nonfinite_clock", "now must be finite numeric and not bool", raise_on_error)

    # -------------------------------------------------------------------------
    # 2. Root Policy Contract Validation
    # -------------------------------------------------------------------------
    enabled = policy.get("enabled")
    if not is_strict_bool(enabled):
        return _fail("malformed_policy", "policy.enabled must be a strict bool", raise_on_error)

    policy_id = policy.get("policy_id")
    if not isinstance(policy_id, str) or not policy_id.strip():
        return _fail("malformed_policy", "policy.policy_id must be a non-empty string", raise_on_error)

    allowed_repos = policy.get("allowed_repos")
    if not isinstance(allowed_repos, list) or not all(isinstance(r, str) and r.strip() for r in allowed_repos):
        return _fail("malformed_policy", "policy.allowed_repos must be a list of non-empty strings", raise_on_error)

    allowed_agents = policy.get("allowed_agents")
    if not isinstance(allowed_agents, list) or not all(is_canonical_uuid(a) for a in allowed_agents):
        return _fail("malformed_policy", "policy.allowed_agents must be a list of canonical UUIDs", raise_on_error)

    policy_company_id = policy.get("company_id")
    if not is_canonical_uuid(policy_company_id):
        return _fail("malformed_policy", "policy.company_id must be a canonical UUID", raise_on_error)

    policy_project_id = policy.get("project_id")
    if not is_canonical_uuid(policy_project_id):
        return _fail("malformed_policy", "policy.project_id must be a canonical UUID", raise_on_error)

    max_retries = policy.get("max_retries")
    if not is_strict_int(max_retries) or not (0 <= max_retries <= 2):
        return _fail("malformed_policy", "policy.max_retries must be an int between 0 and 2", raise_on_error)

    max_evidence_age = policy.get("max_evidence_age")
    if not is_strict_finite_number(max_evidence_age) or not (1.0 <= max_evidence_age <= 60.0):
        return _fail("malformed_policy", "policy.max_evidence_age must be finite numeric between 1.0 and 60.0", raise_on_error)

    # -------------------------------------------------------------------------
    # 3. Expected Binding Contract Validation
    # -------------------------------------------------------------------------
    for field in IDENTITY_FIELDS:
        if not is_canonical_uuid(expected.get(field)):
            return _fail("malformed_expected", f"expected.{field} must be a canonical UUID", raise_on_error)

    repo = expected.get("repo")
    if not isinstance(repo, str) or not repo.strip():
        return _fail("malformed_expected", "expected.repo must be a non-empty string", raise_on_error)

    retries_used = expected.get("retries_used")
    if not is_strict_int(retries_used) or retries_used < 0:
        return _fail("malformed_expected", "expected.retries_used must be a non-negative int", raise_on_error)

    # -------------------------------------------------------------------------
    # 4. Evidence Contract Validation
    # -------------------------------------------------------------------------
    for field in IDENTITY_FIELDS:
        if not is_canonical_uuid(evidence.get(field)):
            return _fail("malformed_evidence", f"evidence.{field} must be a canonical UUID", raise_on_error)

    observed_at = evidence.get("observed_at")
    if not is_strict_finite_number(observed_at):
        return _fail("nonfinite_clock", "evidence.observed_at must be finite numeric and not bool", raise_on_error)

    native_status = evidence.get("native_status")
    if not _member(native_status, VALID_NATIVE_STATUSES):
        return _fail("malformed_evidence", "invalid evidence.native_status", raise_on_error)

    cleanup_complete = evidence.get("cleanup_complete")
    if not is_strict_bool(cleanup_complete):
        return _fail("malformed_evidence", "evidence.cleanup_complete must be a strict bool", raise_on_error)

    other_run_active = evidence.get("other_run_active")
    if not is_strict_bool(other_run_active):
        return _fail("malformed_evidence", "evidence.other_run_active must be a strict bool", raise_on_error)

    provider_started = evidence.get("provider_started")
    if provider_started is not None and not is_strict_bool(provider_started):
        return _fail("malformed_evidence", "evidence.provider_started must be bool or None", raise_on_error)

    effects = evidence.get("effects")
    if not _member(effects, VALID_EFFECTS):
        return _fail("malformed_evidence", "invalid evidence.effects", raise_on_error)

    attestation = evidence.get("attestation")
    if not _member(attestation, VALID_ATTESTATIONS):
        return _fail("malformed_evidence", "invalid evidence.attestation", raise_on_error)

    recovery_action_id = evidence.get("recovery_action_id")
    if recovery_action_id is not None and not is_canonical_uuid(recovery_action_id):
        return _fail("malformed_evidence", "evidence.recovery_action_id must be canonical UUID or None", raise_on_error)

    error_kind = evidence.get("error_kind")
    if not _member(error_kind, VALID_ERROR_KINDS):
        return _fail("malformed_evidence", "invalid evidence.error_kind", raise_on_error)

    paused = evidence.get("paused")
    if not is_strict_bool(paused):
        return _fail("malformed_evidence", "evidence.paused must be a strict bool", raise_on_error)

    terminated = evidence.get("terminated")
    if not is_strict_bool(terminated):
        return _fail("malformed_evidence", "evidence.terminated must be a strict bool", raise_on_error)

    new_run = evidence.get("new_run")
    if new_run is not None and not isinstance(new_run, dict):
        return _fail("malformed_evidence", "evidence.new_run must be None or dict", raise_on_error)

    # -------------------------------------------------------------------------
    # 5. Root Policy Scope & Disabled Enforcement
    # -------------------------------------------------------------------------
    if not enabled:
        return {"action": "block", "code": "policy_disabled"}

    if expected["company_id"] != policy_company_id or expected["project_id"] != policy_project_id:
        return {"action": "block", "code": "scope_company_project_mismatch"}

    if repo not in allowed_repos:
        return {"action": "block", "code": "repo_not_allowed"}

    if expected["agent_id"] not in allowed_agents:
        return {"action": "block", "code": "agent_not_allowed"}

    # -------------------------------------------------------------------------
    # 6. Clocks & Freshness Enforcement
    # -------------------------------------------------------------------------
    if observed_at > now:
        return {"action": "block", "code": "future_evidence"}

    if (now - observed_at) > max_evidence_age:
        return {"action": "block", "code": "stale_evidence"}

    # -------------------------------------------------------------------------
    # 7. Exact Identity Binding Enforcement
    # -------------------------------------------------------------------------
    for field in IDENTITY_FIELDS:
        if evidence[field] != expected[field]:
            return {"action": "block", "code": "identity_mismatch"}

    # -------------------------------------------------------------------------
    # 8. Terminal Refusal States (Paused / Terminated / Security / Quota / Auth)
    # -------------------------------------------------------------------------
    if paused:
        return {"action": "block", "code": "paused"}

    if terminated:
        return {"action": "block", "code": "terminated"}

    if error_kind == "auth":
        return {"action": "block", "code": "auth_error"}

    if error_kind == "quota":
        return {"action": "block", "code": "quota_error"}

    if error_kind == "security":
        return {"action": "block", "code": "security_error"}

    # -------------------------------------------------------------------------
    # 9. Successor Run Adoption (evidence.new_run)
    # -------------------------------------------------------------------------
    if new_run is not None:
        nr_id = new_run.get("id")
        nr_status = new_run.get("status")
        nr_task_id = new_run.get("task_id")
        nr_issue_id = new_run.get("issue_id")
        nr_agent_id = new_run.get("agent_id")
        nr_company_id = new_run.get("company_id")
        nr_project_id = new_run.get("project_id")
        nr_source_run_id = new_run.get("source_run_id")
        nr_recovery_action_id = new_run.get("recovery_action_id")

        if (
            is_canonical_uuid(nr_id)
            and nr_id != expected["source_run_id"]
            and cleanup_complete
            and not other_run_active
            and _member(nr_status, VALID_BIND_STATUSES)
            and nr_task_id == expected["task_id"]
            and nr_issue_id == expected["issue_id"]
            and nr_agent_id == expected["agent_id"]
            and nr_company_id == expected["company_id"]
            and nr_project_id == expected["project_id"]
            and nr_source_run_id == expected["source_run_id"]
            and is_canonical_uuid(recovery_action_id)
            and nr_recovery_action_id == recovery_action_id
        ):
            return {"action": "bind", "code": "bind_successor"}
        return {"action": "block", "code": "successor_mismatch"}

    # -------------------------------------------------------------------------
    # 10. Active Runs / Busy Slots / Unproven Cleanup -> WAIT
    # -------------------------------------------------------------------------
    if other_run_active:
        return {"action": "wait", "code": "other_run_active"}

    if not cleanup_complete:
        return {"action": "wait", "code": "cleanup_incomplete"}

    if native_status in ("queued", "running", "unknown"):
        return {"action": "wait", "code": f"status_{native_status}"}

    # -------------------------------------------------------------------------
    # 11. Native Succeeded -> RECEIVE
    # -------------------------------------------------------------------------
    if native_status == "succeeded":
        return {"action": "receive", "code": "native_succeeded"}

    # -------------------------------------------------------------------------
    # 12. Terminal Failure / Refusal / Retry Evaluation
    # -------------------------------------------------------------------------
    if native_status == "cancelled":
        # Cancelled is never reclassified as success or eligible for auto-retry
        return {"action": "block", "code": "cancelled"}

    if native_status in ("failed", "timed_out"):
        # Provider started or unknown must block unknown effects
        if provider_started is not False:
            return {"action": "block", "code": "unknown_effects"}

        # Effects must be explicitly not_performed
        if effects != "not_performed":
            return {"action": "block", "code": "unknown_effects"}

        # Attestation must be trusted pre-provider v1
        if attestation != "trusted_pre_provider_v1":
            return {"action": "block", "code": "untrusted_attestation"}

        # Error kind must be pre_provider_transient
        if error_kind == "provider_failure":
            return {"action": "block", "code": "provider_failure"}
        if error_kind != "pre_provider_transient":
            return {"action": "block", "code": "non_retryable_error"}

        # Matching valid native recovery action required
        if not is_canonical_uuid(recovery_action_id):
            return {"action": "block", "code": "missing_recovery_action"}

        # Check retry budget
        if retries_used >= max_retries:
            return {"action": "block", "code": "retry_budget_exhausted"}

        # All strict preconditions satisfied for safe retry
        return {"action": "retry", "code": "retry_pre_provider_transient"}

    return {"action": "block", "code": "unhandled_condition"}
