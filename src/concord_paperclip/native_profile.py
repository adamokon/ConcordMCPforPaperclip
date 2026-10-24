"""Native macOS Seatbelt profile and clean Cargo environment generator."""

import json
import unicodedata

PROHIBITED_ROOTS = {
    "/",
    "/Users",
    "/Volumes",
    "/System",
    "/Library",
    "/private",
    "/private/var",
    "/usr",
}


class NativePolicyError(ValueError):
    """Raised when policy arguments violate lexical safety constraints."""


def validate_path(p: str) -> str:
    if not isinstance(p, str):
        raise NativePolicyError(f"Path must be a string, got {type(p).__name__}")
    if not p:
        raise NativePolicyError("Path must not be empty")
    if len(p) > 2048:
        raise NativePolicyError("Path length exceeds 2048 characters")
    if not p.startswith("/"):
        raise NativePolicyError("Path must be an absolute POSIX path")
    if p.endswith("/"):
        raise NativePolicyError("Path must not have a trailing slash")
    if "//" in p:
        raise NativePolicyError("Path must not contain duplicate slashes")
    if "\\" in p:
        raise NativePolicyError("Path must not contain backslashes")
    if any(part in (".", "..") for part in p.split("/")):
        raise NativePolicyError("Path must not contain dot or dot-dot components")
    if any(unicodedata.category(c) in ("Cc", "Cs") for c in p):
        raise NativePolicyError("Path contains Unicode control or surrogate characters")
    if p in PROHIBITED_ROOTS:
        raise NativePolicyError(f"Path specifies an overly broad root: {p}")
    return p


def _quote(path: str) -> str:
    return json.dumps(path, ensure_ascii=False)


def profile(workspace: str, toolchain: str, developer: str) -> str:
    ws = validate_path(workspace)
    tc = validate_path(toolchain)
    dev = validate_path(developer)
    q_ws = _quote(ws)
    q_tc = _quote(tc)
    q_dev = _quote(dev)
    lines = [
        "(version 1)",
        "(deny default)",
        "(allow process-exec process-fork sysctl-read file-read-metadata)",
        "(allow signal (target self) (target children))",
        f'(allow file-read* (subpath "/System/Library") (subpath "/System/Volumes/Preboot/Cryptexes/OS") (subpath "/usr/bin") (subpath "/usr/sbin") (subpath "/usr/lib") (subpath "/usr/libexec") (subpath "/usr/share") (subpath {q_dev}) (subpath {q_tc}) (subpath {q_ws}))',
        '(allow file-read* (literal "/") (literal "/dev/null") (literal "/dev/random") (literal "/dev/urandom") (literal "/private/etc/localtime") (literal "/private/etc/ssl/openssl.cnf"))',
        f'(allow file-write* (subpath {q_ws}) (literal "/dev/null"))',
        "(deny network*)",
    ]
    return "\n".join(lines) + "\n"


def environment(workspace: str, toolchain: str, sdk: str) -> dict[str, str]:
    ws = validate_path(workspace)
    tc = validate_path(toolchain)
    sdk_path = validate_path(sdk)
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": f"{ws}/home",
        "CARGO_HOME": f"{ws}/cargo-home",
        "TMPDIR": f"{ws}/tmp",
        "RUSTC": f"{tc}/bin/rustc",
        "RUSTDOC": f"{tc}/bin/rustdoc",
        "SDKROOT": sdk_path,
        "LANG": "C.UTF-8",
    }
