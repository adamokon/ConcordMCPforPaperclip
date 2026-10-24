"""Readiness assessment from a trusted operator probe.

Assesses readiness from a trusted operator probe without inferring
provider quota or OAuth freshness from idle.
"""

import math
from typing import Any, Dict

# Listed required keys in a valid probe.
REQUIRED_KEYS = {
    "observed_at",
    "agent_status",
    "adapter_type",
    "enrolled",
    "environment_empty",
    "active_runs",
    "oauth_present",
    "provider_auth",
    "provider_quota",
}

VALID_AUTH = {"unknown", "ok", "expired"}
VALID_QUOTA = {"unknown", "available", "exhausted"}


def _is_finite_numeric(val: Any) -> bool:
    """Check if val is an int or float, not a bool, and is finite."""
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return False
    try:
        return math.isfinite(val)
    except (TypeError, OverflowError, ValueError):
        return False


def _is_nonnegative_int(val: Any) -> bool:
    """Check if val is a nonnegative int, not a bool, without numeric overflow."""
    if isinstance(val, bool) or not isinstance(val, int):
        return False
    if val < 0:
        return False
    try:
        float(val)
    except (OverflowError, ValueError):
        return False
    return True


def evaluate(probe: dict, now: float, max_age: float = 60) -> Dict[str, Any]:
    """Evaluate probe readiness.

    Parameters:
        probe: dict containing operator probe data.
        now: current timestamp (finite numeric, not bool).
        max_age: maximum allowed probe age (finite numeric > 0, not bool).

    Returns:
        dict with keys:
            eligible (bool): whether the agent is ready for work.
            code (str): readiness status or rejection code.
            auth (str): provider auth state.
            quota (str): provider quota state.
    """
    try:
        # Validate probe type
        if not isinstance(probe, dict):
            return {
                "eligible": False,
                "code": "INVALID_PROBE",
                "auth": "unknown",
                "quota": "unknown",
            }

        # Validate now and max_age
        if not _is_finite_numeric(now):
            return {
                "eligible": False,
                "code": "INVALID_PROBE",
                "auth": "unknown",
                "quota": "unknown",
            }

        if not _is_finite_numeric(max_age) or max_age <= 0:
            return {
                "eligible": False,
                "code": "INVALID_PROBE",
                "auth": "unknown",
                "quota": "unknown",
            }

        native = probe.get("adapter_type") == "codex_local"
        required = REQUIRED_KEYS - {"oauth_present"} if native else REQUIRED_KEYS
        # Native availability comes from a fresh trusted probe, never AGY OAuth.
        if not required.issubset(probe):
            return {
                "eligible": False,
                "code": "INVALID_PROBE",
                "auth": "unknown",
                "quota": "unknown",
            }

        observed_at = probe["observed_at"]
        if not _is_finite_numeric(observed_at):
            return {
                "eligible": False,
                "code": "INVALID_PROBE",
                "auth": "unknown",
                "quota": "unknown",
            }

        agent_status = probe["agent_status"]
        if not isinstance(agent_status, str):
            return {
                "eligible": False,
                "code": "INVALID_PROBE",
                "auth": "unknown",
                "quota": "unknown",
            }

        adapter_type = probe["adapter_type"]
        if not isinstance(adapter_type, str):
            return {
                "eligible": False,
                "code": "INVALID_PROBE",
                "auth": "unknown",
                "quota": "unknown",
            }

        enrolled = probe["enrolled"]
        if not isinstance(enrolled, bool):
            return {
                "eligible": False,
                "code": "INVALID_PROBE",
                "auth": "unknown",
                "quota": "unknown",
            }

        environment_empty = probe["environment_empty"]
        if not isinstance(environment_empty, bool):
            return {
                "eligible": False,
                "code": "INVALID_PROBE",
                "auth": "unknown",
                "quota": "unknown",
            }

        active_runs = probe["active_runs"]
        if not _is_nonnegative_int(active_runs):
            return {
                "eligible": False,
                "code": "INVALID_PROBE",
                "auth": "unknown",
                "quota": "unknown",
            }

        oauth_present = True if native else probe["oauth_present"]
        if not isinstance(oauth_present, bool):
            return {
                "eligible": False,
                "code": "INVALID_PROBE",
                "auth": "unknown",
                "quota": "unknown",
            }

        provider_auth = probe["provider_auth"]
        if provider_auth not in VALID_AUTH:
            return {
                "eligible": False,
                "code": "INVALID_PROBE",
                "auth": "unknown",
                "quota": "unknown",
            }

        provider_quota = probe["provider_quota"]
        if provider_quota not in VALID_QUOTA:
            return {
                "eligible": False,
                "code": "INVALID_PROBE",
                "auth": "unknown",
                "quota": "unknown",
            }

        # Calculate probe age; check overflow
        try:
            age = now - observed_at
            if not math.isfinite(age):
                return {
                    "eligible": False,
                    "code": "INVALID_PROBE",
                    "auth": "unknown",
                    "quota": "unknown",
                }
        except (OverflowError, TypeError):
            return {
                "eligible": False,
                "code": "INVALID_PROBE",
                "auth": "unknown",
                "quota": "unknown",
            }

        # Precedence 1: Reject stale observed_at older than max_age or future
        if observed_at > now or age > max_age:
            return {
                "eligible": False,
                "code": "STALE_PROBE",
                "auth": provider_auth,
                "quota": provider_quota,
            }

        # Precedence 2: Disabled states not idle/active -> AGENT_UNAVAILABLE
        if agent_status not in ("idle", "active"):
            return {
                "eligible": False,
                "code": "AGENT_UNAVAILABLE",
                "auth": provider_auth,
                "quota": provider_quota,
            }

        # Precedence 3: adapter_type != process -> UNSUPPORTED_ADAPTER
        if adapter_type not in {"process", "codex_local"}:
            return {
                "eligible": False,
                "code": "UNSUPPORTED_ADAPTER",
                "auth": provider_auth,
                "quota": provider_quota,
            }

        # Precedence 4: enrolled false -> NOT_ENROLLED
        if not enrolled:
            return {
                "eligible": False,
                "code": "NOT_ENROLLED",
                "auth": provider_auth,
                "quota": provider_quota,
            }

        # Precedence 5: unavailable credential/OAuth or expired auth -> AUTH_REQUIRED
        if (
            (native and probe.get("credential_available") is not True)
            or not oauth_present
            or provider_auth == "expired"
        ):
            return {
                "eligible": False,
                "code": "AUTH_REQUIRED",
                "auth": provider_auth,
                "quota": provider_quota,
            }

        # Precedence 6: active_runs > 0 or environment_empty false -> BUSY
        if active_runs > 0 or not environment_empty:
            return {
                "eligible": False,
                "code": "BUSY",
                "auth": provider_auth,
                "quota": provider_quota,
            }

        # Precedence 7: provider_quota exhausted -> QUOTA_EXHAUSTED
        if provider_quota == "exhausted":
            return {
                "eligible": False,
                "code": "QUOTA_EXHAUSTED",
                "auth": provider_auth,
                "quota": provider_quota,
            }

        # Otherwise code READY eligible true; preserve auth/quota uncertainty
        return {
            "eligible": True,
            "code": "READY",
            "auth": provider_auth,
            "quota": provider_quota,
        }

    except Exception:
        return {
            "eligible": False,
            "code": "INVALID_PROBE",
            "auth": "unknown",
            "quota": "unknown",
        }
