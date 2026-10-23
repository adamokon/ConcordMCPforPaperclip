"""Pure scope and scheduling policies; no production identities or model defaults."""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath


class BridgeError(Exception):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(f"{code}: {message}" if message else code)


def relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise BridgeError("INVALID_PATH")
    if value.startswith("/") or "\\" in value or any(ord(c) < 32 for c in value):
        raise BridgeError("INVALID_PATH")
    if any(part in ("", ".", "..") for part in value.rstrip("/").split("/")):
        raise BridgeError("INVALID_PATH")
    if any(c in value for c in "*?[]:"):
        raise BridgeError("INVALID_PATH", "Use exact files or directory prefixes ending in /")
    parts = PurePosixPath(value).parts
    if any(p.lower() in {".git", ".ssh", ".gemini", ".env", "site-private"} for p in parts):
        raise BridgeError("PRIVATE_PATH")
    return value


def contains(scope: str, path: str) -> bool:
    return path.startswith(scope) if scope.endswith("/") else path == scope


def overlap(a: str, b: str) -> bool:
    return contains(a, b) or contains(b, a)


def scopes(values: list[str]) -> list[str]:
    if not isinstance(values, list) or not 1 <= len(values) <= 128:
        raise BridgeError("INVALID_SCOPE")
    return sorted({relative_path(v) for v in values})


@dataclass(frozen=True)
class Principal:
    """Bound by the process owner, never supplied by an MCP tool argument."""

    name: str
    role: str = "coordinator"
    task_ids: tuple[str, ...] = ()

    def require(self, *roles: str) -> None:
        if self.role not in roles:
            raise BridgeError("FORBIDDEN")

    def access(self, task_id: str, owner: str) -> None:
        if self.role == "coordinator" and self.name == owner:
            return
        if task_id not in self.task_ids:
            raise BridgeError("FORBIDDEN")


def classify_failure(source: str, code: str, provider_confirmed: bool = False) -> str:
    """HTTP 429/RESOURCE_EXHAUSTED alone might refer to a proxy or host resources."""
    if source == "model_provider" and provider_confirmed and code in {"quota_exceeded", "rate_limit_exceeded"}:
        return "confirmed_quota"
    return {
        "invalid_grant": "authentication", "unauthenticated": "authentication",
        "timeout": "timeout", "network_error": "network", "checkout_conflict": "conflict",
        "test_failed": "tests", "permission_denied": "access",
    }.get(code, "unknown")


def tokenish(data: bytes) -> bool:
    # Conservative extra guard, not a DLP guarantee. Use synthetic/public inputs.
    return bool(re.search(
        rb"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----|(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{16,}"
        rb"|ya29\.[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._~+/-]{16,}"
        rb"|[\"'](?:refresh_token|client_secret|access_token)[\"']\s*:\s*[\"'][^\"']{8,}", data
    ))
