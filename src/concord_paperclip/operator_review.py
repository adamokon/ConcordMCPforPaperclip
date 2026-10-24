"""Opt-in operator-policy capability. No operator credential enters the bridge.

The fixed hook is a separately provisioned trusted boundary, not an agent API
fallback. It must independently validate this exact request against trusted
receipts, tests and review intent before using the owner-board accept endpoint.
"""

import hashlib

from .policy import BridgeError
from .store import canonical

CONTRACT = "operator-policy-native-accept-v1"


def configuration(config):
    value = config.get("native_completion")
    if (not isinstance(value, dict) or set(value) != {"contract", "command", "policy_id", "user_id"}
            or value.get("contract") != CONTRACT
            or not isinstance(value.get("command"), list) or not value["command"]
            or not all(isinstance(x, str) and x and "\0" not in x for x in value["command"])
            or not all(isinstance(value.get(k), str) and value[k].strip() and "\0" not in value[k]
                       for k in ("policy_id", "user_id"))):
        raise BridgeError("OPERATOR_REVIEW_CAPABILITY_REQUIRED")
    return value


def request(policy, task, row, manifest, submission, tests, reviews):
    return dict(version=1, contract=CONTRACT, action="accept_exact_completion_review",
                audit_actor="operator-policy", policy_id=policy["policy_id"], user_id=policy["user_id"],
                task_id=task["id"], issue_id=task["issue_id"], interaction_id=row["id"],
                card=row, manifest=manifest, manifest_digest=digest(manifest), submission=submission,
                independent_tests=tests, reviews=reviews)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def invoke(policy, value):
    from .fixed_command import call
    result = call(policy["command"], value)
    expected = dict(version=1, contract=CONTRACT, audit_actor="operator-policy",
                    policy_id=policy["policy_id"], user_id=policy["user_id"],
                    request_sha256=digest(value), interaction_id=value["interaction_id"], status="accepted")
    if result != expected:
        raise BridgeError("OPERATOR_REVIEW_RECEIPT_MISMATCH")
    return result


def confirmed(row, policy):
    if (row.get("status") != "accepted" or row.get("resolvedByUserId") != policy["user_id"]
            or row.get("resolvedByAgentId") or row.get("resolvedByRunId")):
        raise BridgeError("OPERATOR_ACCEPT_NOT_CONFIRMED")
