"""executor_contract.py - Repository build executor contract validation."""

import copy
import urllib.parse

KNOWN_TARGETS = {"aarch64-apple-darwin", "x86_64-apple-darwin", "x86_64-unknown-linux-gnu"}
DARWIN_TARGETS = {"aarch64-apple-darwin", "x86_64-apple-darwin"}
KNOWN_RECIPES = {"cargo-check", "cargo-test", "macos-filesystem"}
FORBIDDEN_NAMES = (".git", ".ssh", ".gemini", ".env")
GLOB_CHARS = set("*?[]{}")

REQ_KEYS = {"schema_version", "source_url", "commit", "target", "checks", "allowed_paths", "max_files", "max_bytes"}
CAP_KEYS = {"schema_version", "targets", "recipes", "repository_transport", "credential_free_verifier", "max_files", "max_bytes", "source_urls", "execution_target"}


class ContractError(ValueError):
    """Raised when contract validation fails."""


def _validate_url(url):
    if type(url) is not str or not (1 <= len(url) <= 2048) or any(ord(c) < 33 or ord(c) == 127 for c in url):
        raise ContractError("Invalid source URL")
    try:
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment
                or not parsed.path.endswith(".git") or parsed.port not in (None, 443)):
            raise ContractError("Source must be an HTTPS Git URL without credentials, query or fragment")
    except ValueError as error:
        raise ContractError("Invalid source URL") from error


def _validate_cap(cap):
    if type(cap) is not dict or set(cap.keys()) != CAP_KEYS:
        raise ContractError("Invalid capabilities keys or type")
    if type(cap["schema_version"]) is not int or cap["schema_version"] != 1:
        raise ContractError("Capabilities schema_version must be int 1")
    if type(cap["repository_transport"]) is not bool or not cap["repository_transport"]:
        raise ContractError("Capabilities repository_transport must be True")
    if type(cap["credential_free_verifier"]) is not bool or not cap["credential_free_verifier"]:
        raise ContractError("Capabilities credential_free_verifier must be True")
    if type(cap["max_files"]) is not int or not (1 <= cap["max_files"] <= 100000):
        raise ContractError("Capabilities max_files out of bounds")
    if type(cap["max_bytes"]) is not int or not (1 <= cap["max_bytes"] <= 1073741824):
        raise ContractError("Capabilities max_bytes out of bounds")
    if type(cap["execution_target"]) is not str or cap["execution_target"] not in KNOWN_TARGETS:
        raise ContractError("Invalid execution target")
    urls = cap["source_urls"]
    if type(urls) is not list or not (1 <= len(urls) <= 32):
        raise ContractError("Invalid trusted source allowlist")
    for url in urls:
        _validate_url(url)
    if len(urls) != len(set(urls)):
        raise ContractError("Duplicate trusted source URL")
    for key, known in (("targets", KNOWN_TARGETS), ("recipes", KNOWN_RECIPES)):
        val = cap[key]
        if type(val) is not list or not (1 <= len(val) <= len(known)):
            raise ContractError(f"Capabilities {key} must be nonempty list")
        if any(type(item) is not str or item not in known for item in val):
            raise ContractError(f"Capabilities {key} contains invalid items")
        if len(val) != len(set(val)):
            raise ContractError(f"Capabilities {key} contains duplicates")


def _validate_path(path):
    if type(path) is not str or not (1 <= len(path) <= 1024):
        raise ContractError("Invalid path type or length")
    if any(ord(c) < 32 or ord(c) == 127 for c in path):
        raise ContractError("Control characters forbidden in allowed_paths")
    if path.startswith("/") or "\\" in path or ":" in path or any(c in GLOB_CHARS for c in path):
        raise ContractError("Unsafe or absolute path in allowed_paths")
    raw = path[:-1] if path.endswith("/") else path
    if not raw:
        raise ContractError("Empty path component in allowed_paths")
    parts = raw.split("/")
    if any(not part or part in (".", "..") for part in parts):
        raise ContractError("Invalid empty or traversal component in allowed_paths")
    if any(part.casefold() in FORBIDDEN_NAMES for part in parts):
        raise ContractError("Forbidden private path component in allowed_paths")
    if any(0xD800 <= ord(c) <= 0xDFFF for c in path):
        raise ContractError("Invalid Unicode path")


def validate_request(request, capabilities) -> dict:
    _validate_cap(capabilities)
    if type(request) is not dict or set(request.keys()) != REQ_KEYS:
        raise ContractError("Invalid request keys or type")
    if type(request["schema_version"]) is not int or request["schema_version"] != 1:
        raise ContractError("Request schema_version must be int 1")

    url = request["source_url"]
    _validate_url(url)
    if url not in capabilities["source_urls"]:
        raise ContractError("Source URL not allowed by trusted operator policy")

    commit = request["commit"]
    if type(commit) is not str or len(commit) != 40 or not all(c in "0123456789abcdef" for c in commit):
        raise ContractError("commit must be 40 lowercase hex characters")

    target = request["target"]
    if type(target) is not str or target not in KNOWN_TARGETS or target not in capabilities["targets"]:
        raise ContractError(f"Unsupported target: {target}")

    checks = request["checks"]
    if type(checks) is not list or not (1 <= len(checks) <= len(KNOWN_RECIPES)):
        raise ContractError("checks must be nonempty list")
    for check in checks:
        if type(check) is not str or check not in KNOWN_RECIPES or check not in capabilities["recipes"]:
            raise ContractError(f"Unsupported recipe check: {check}")
    if len(checks) != len(set(checks)):
        raise ContractError("checks must be unique")
    if "macos-filesystem" in checks and target not in DARWIN_TARGETS:
        raise ContractError("macos-filesystem recipe requires a Darwin target")
    if "macos-filesystem" in checks and capabilities["execution_target"] != target:
        raise ContractError("macos-filesystem requires the matching native Darwin executor")

    paths = request["allowed_paths"]
    if type(paths) is not list or not (1 <= len(paths) <= 128):
        raise ContractError("allowed_paths must be nonempty list max 128 items")
    for p in paths:
        _validate_path(p)
    if len(paths) != len(set(paths)):
        raise ContractError("allowed_paths must be unique")

    max_files = request["max_files"]
    if type(max_files) is not int or not (1 <= max_files <= capabilities["max_files"]):
        raise ContractError("max_files must be positive integer within capability limits")

    max_bytes = request["max_bytes"]
    if type(max_bytes) is not int or not (1 <= max_bytes <= capabilities["max_bytes"]):
        raise ContractError("max_bytes must be positive integer within capability limits")

    return copy.deepcopy(request)
