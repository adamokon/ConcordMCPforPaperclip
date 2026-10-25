"""Fail-closed decisions over trusted observations; never execution authority."""

import math
import re
import unicodedata

_UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_BIND = ("task_id", "issue_id", "run_id", "agent_id")
_FIELDS = {
    "schema_version",
    "kind",
    "reason",
    "complete",
    "binding",
    "snapshot_digest",
    "present_paths",
    "missing_paths",
}


def _uuid(value):
    return type(value) is str and _UUID.fullmatch(value) is not None


def _number(value, minimum):
    return type(value) in (int, float) and minimum <= value <= 2**53 - 1 and math.isfinite(value)


def classify_partial(facts):
    """True permits bounded read-only harvest/cleanup, never retry or success.

    task_cancelled does not authorize reopening a task. Callers must independently
    bind native scopes, producer ownership and hashes before reading any file.
    """

    def no(code):
        return {"eligible": False, "code": code}

    if type(facts) is not dict:
        return no("invalid_facts")
    f = facts
    if not (
        _uuid(f.get("run_id")) and _uuid(f.get("expected_run_id")) and f["run_id"] == f["expected_run_id"]
    ):
        return no("invalid_run_binding")
    if (
        type(f.get("worker_status")) is not str
        or f["worker_status"] != "error"
        or type(f.get("worker_exit_code")) is not int
        or f["worker_exit_code"] != 1
        or type(f.get("worker_denied_actions")) is not list
        or f["worker_denied_actions"] != []
    ):
        return no("invalid_worker_outcome")
    if type(f.get("native_status")) is not str or f["native_status"] not in ("failed", "succeeded"):
        return no("unsafe_native_status")
    if not (_number(f.get("elapsed_seconds"), 0) and _number(f.get("deadline_seconds"), 1)):
        return no("invalid_timing")
    if f["elapsed_seconds"] < f["deadline_seconds"]:
        return no("deadline_not_reached")
    for name in (
        "timeout_observed",
        "provider_stopped",
        "environment_removed",
        "producer_verified",
        "allowed_scope",
    ):
        if f.get(name) is not True:
            return no("missing_" + name)
    for name in ("auth_error", "quota_error", "security_error"):
        if f.get(name) is not False:
            return no("unsafe_" + name)
    if type(f.get("task_cancelled")) is not bool:
        return no("invalid_task_cancelled")
    if type(f.get("outer_timeout")) is not bool:
        return no("invalid_outer_timeout")
    if type(f.get("file_count")) is not int or not 1 <= f["file_count"] <= 128:
        return no("invalid_file_count")
    status = f.get("cli_status")
    if "cli_status" not in f:
        return no("missing_cli_status")
    if type(status) is str and status == "SUCCESS":
        if f.get("cli_response_empty") is not True:
            return no("nonempty_or_unknown_response")
    elif status is None and f["outer_timeout"] is True:
        pass
    else:
        return no("unsafe_cli_outcome")
    return {"eligible": True, "code": "partial_final_response_timeout"}


def _paths(value, nonempty):
    if type(value) is not list or not (int(nonempty) <= len(value) <= 128):
        return False
    seen = set()
    for path in value:
        if (
            type(path) is not str
            or not path
            or path.startswith("/")
            or any(c in path for c in "\\*?[]:")
            or any(unicodedata.category(c).startswith("C") for c in path)
        ):
            return False
        parts = path.split("/")
        if any(
            p.lower() in ("", ".", "..", ".ssh", ".git", "site-private") or p.lower().startswith(".env")
            for p in parts
        ):
            return False
        if path in seen:
            return False
        seen.add(path)
    return True


def validate_partial_record(record, expected):
    """Validate metadata only; no contents, authority, or success are implied."""
    if type(record) is not dict or type(expected) is not dict:
        return False
    if set(record) != _FIELDS:
        return False
    if (
        type(record["schema_version"]) is not int
        or record["schema_version"] != 1
        or type(record["kind"]) is not str
        or record["kind"] != "partial"
        or type(record["reason"]) is not str
        or record["reason"] != "final_response_timeout"
        or record["complete"] is not False
    ):
        return False
    binding = record["binding"]
    if type(binding) is not dict or set(binding) != set(_BIND):
        return False
    for key in _BIND:
        if not (_uuid(binding[key]) and _uuid(expected.get(key)) and binding[key] == expected[key]):
            return False
    digest = record["snapshot_digest"]
    if type(digest) is not str or _HEX.fullmatch(digest) is None:
        return False
    present, missing = record["present_paths"], record["missing_paths"]
    paths = expected.get("paths")
    if not (_paths(present, True) and _paths(missing, False) and _paths(paths, True)):
        return False
    p, m = set(present), set(missing)
    return (
        not p.intersection(m) and p.union(m) == set(paths) and any(path.endswith(".py") for path in present)
    )
