"""Native, credential-free macOS Cargo verification. Run through a trusted root CLI.

The operator owns policy and recipes. Source bytes are data, never Python imports.
Paperclip remains responsible for task assignment; this module is not a scheduler.
"""

import argparse
import ctypes
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import pwd
import re
import signal
import shutil
import stat
import subprocess
import sys
import time
import uuid

from .bounded_process import run_bounded
from .native_profile import environment, profile
from .source_snapshot import MAX_RAW_SIZE, decode_snapshot, materialize_files


class NativeExecutionError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _root_path(value, directory=True):
    if not isinstance(value, str) or not value.startswith("/"):
        raise NativeExecutionError("Absolute operator path required")
    path = Path(value)
    if path.resolve(strict=True) != path or (directory and not path.is_dir()):
        raise NativeExecutionError("Canonical real path required")
    for item in (path, *path.parents):
        st = item.stat()
        sticky_parent = item != path and stat.S_ISDIR(st.st_mode) and bool(st.st_mode & stat.S_ISVTX)
        if st.st_uid != 0 or (st.st_mode & 0o022 and not sticky_parent):
            raise NativeExecutionError("Operator path must be root owned and not writable by others")
    return path


def load_policy(path):
    path = _root_path(path, directory=False)
    if not path.is_file() or path.stat().st_size > 16384:
        raise NativeExecutionError("Invalid policy file")
    policy = json.loads(path.read_text())
    keys = {"work_root", "toolchain", "developer", "sdk", "uid", "gid", "target", "timeout", "max_output"}
    if type(policy) is not dict or set(policy) != keys:
        raise NativeExecutionError("Invalid policy schema")
    for name in ("work_root", "toolchain", "developer", "sdk"):
        _root_path(policy[name])
    for name in ("uid", "gid"):
        if type(policy[name]) is not int or policy[name] <= 0:
            raise NativeExecutionError("Non-root build identity required")
    timeout = policy["timeout"]
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not (0 < timeout <= 1800):
        raise NativeExecutionError("Invalid operator timeout")
    if type(policy["max_output"]) is not int or not (1 <= policy["max_output"] <= 4194304):
        raise NativeExecutionError("Invalid operator log limit")
    account = pwd.getpwuid(policy["uid"])
    if account.pw_gid != policy["gid"] or account.pw_shell not in ("/usr/bin/false", "/sbin/nologin"):
        raise NativeExecutionError("Dedicated non-login build account required")
    host = {"arm64": "aarch64-apple-darwin", "x86_64": "x86_64-apple-darwin"}.get(platform.machine())
    if platform.system() != "Darwin" or policy["target"] != host:
        raise NativeExecutionError("Native Darwin execution target mismatch")
    for tool in ("cargo", "rustc", "rustdoc"):
        _root_path(str(Path(policy["toolchain"]) / "bin" / tool), directory=False)
    for executable in sorted(APPLE_SERVICES):
        verified = subprocess.run(["/usr/bin/codesign", "--verify", "--strict", "-R=anchor apple", executable],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                                  cwd="/", env={"PATH": "/usr/bin:/bin"})
        if verified.returncode:
            raise NativeExecutionError("Protected Apple service signature verification failed")
    return policy


def _executable(pid):
    """Kernel executable identity; argv/ps command text is not an identity check."""
    try:
        library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        library.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        library.proc_pidpath.restype = ctypes.c_int
        buffer = ctypes.create_string_buffer(4096)
        if library.proc_pidpath(pid, buffer, len(buffer)) > 0:
            return buffer.value.decode("utf-8")
    except (OSError, UnicodeError):
        pass
    return None


APPLE_SERVICES = {"/usr/sbin/distnoted", "/usr/sbin/cfprefsd"}


def _uid_inventory(uid):
    out = subprocess.check_output(["/bin/ps", "-axo", "pid=,uid="], text=True,
                                  env={"PATH": "/usr/bin:/bin"}, cwd="/")
    jobs, services = [], []
    for row in out.splitlines():
        parts = row.split()
        if len(parts) != 2 or int(parts[1]) != uid:
            continue
        pid = int(parts[0])
        executable = _executable(pid)
        if executable in APPLE_SERVICES:
            # Per-user Apple daemons may be started by the OS for a new uid.
            # These protected executables are verified during policy preflight.
            services.append(executable)
        else:
            jobs.append(pid)
    return jobs, sorted(set(services))


def _uid_processes(uid):
    return _uid_inventory(uid)[0]


def _cleanup_uid(uid):
    # The global executor lock guarantees that no other job owns this account.
    for _ in range(60):
        remaining = _uid_processes(uid)
        if not remaining:
            return
        for pid in remaining:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        time.sleep(0.05)
    raise NativeExecutionError("Build identity still owns processes; executor remains unavailable")


def _fixture_recipe(toolchain, source, recipe):
    argv = [str(toolchain / "bin" / "cargo")]
    if recipe == "cargo-check":
        argv += ["check"]
    elif recipe in ("cargo-test", "macos-filesystem"):
        argv += ["test"]
    else:
        raise NativeExecutionError("Unknown fixed recipe")
    argv += ["--offline", "--locked", "--manifest-path", str(source / "Cargo.toml")]
    if recipe == "macos-filesystem":
        argv += ["--test", "macos_filesystem"]
    return argv


def execute(raw, digest, policy_path, recipe, task_id, run_id):
    if os.geteuid() != 0:
        raise NativeExecutionError("Trusted root launcher required to drop build identity")
    if not shutil.rmtree.avoids_symlink_attacks:
        raise NativeExecutionError("Symlink-safe workspace cleanup unavailable")
    task_id, run_id = str(uuid.UUID(task_id)), str(uuid.UUID(run_id))
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise NativeExecutionError("Invalid source digest")
    snapshot = decode_snapshot(raw, digest)
    policy = load_policy(policy_path)
    work_root = Path(policy["work_root"])
    policy_hash = hashlib.sha256(canonical(policy)).hexdigest()
    with (work_root / "executor.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if _uid_processes(policy["uid"]):
            raise NativeExecutionError("Build account busy or previous run needs recovery")
        job = work_root / run_id
        job.mkdir(mode=0o711)
        job.chmod(0o711)
        source, workspace = job / "source", job / "workspace"
        materialized = materialize_files(snapshot, source)
        # Preserve Git file modes, but the builder cannot replace input files:
        # every source parent and file is owned by root, outside writable scratch.
        for directory, _, _ in os.walk(source):
            os.chmod(directory, 0o755)
        for entry in materialized["inert_symlinks"]:
            path = source / entry["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(entry["target"], path)
        workspace.mkdir(mode=0o700)
        os.chown(workspace, policy["uid"], policy["gid"])
        for name in ("home", "cargo-home", "tmp", "target"):
            path = workspace / name
            path.mkdir(mode=0o700)
            os.chown(path, policy["uid"], policy["gid"])
        env = environment(str(workspace), policy["toolchain"], policy["sdk"])
        env["CARGO_TARGET_DIR"] = str(workspace / "target")
        sb = profile(str(workspace), policy["toolchain"], policy["developer"])
        sb += f"(allow file-read* (subpath {json.dumps(str(source))}))\n"
        sandbox = job / "sandbox.sb"
        sandbox.write_text(sb)
        sandbox.chmod(0o644)
        argv = ["/usr/bin/sandbox-exec", "-f", str(sandbox)] + _fixture_recipe(Path(policy["toolchain"]), source, recipe)
        try:
            result = run_bounded(argv, str(workspace), env, policy["timeout"], policy["max_output"],
                                 uid=policy["uid"], gid=policy["gid"])
        finally:
            _cleanup_uid(policy["uid"])
            shutil.rmtree(workspace)
            shutil.rmtree(source)
        # The receipt is written by root outside the builder's writable sandbox.
        output = result.pop("output")
        (job / "output.log").write_bytes(output)
        receipt = dict(schema_version=1, task_id=task_id, run_id=run_id, commit=snapshot["commit"],
                       source_sha256=digest, policy_sha256=policy_hash, recipe=recipe,
                       execution_target=policy["target"], build_uid=policy["uid"],
                       credential_free=True, network="deny-all", input_readonly=True,
                       environment_removed=True, **result)
        receipt["system_services_exempted"] = _uid_inventory(policy["uid"])[1]
        receipt["toolchain_sha256"] = {name: hashlib.sha256((Path(policy["toolchain"]) / "bin" / name).read_bytes()).hexdigest()
                                       for name in ("cargo", "rustc", "rustdoc")}
        (job / "receipt.json").write_bytes(canonical(receipt) + b"\n")
        return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--recipe", choices=["cargo-check", "cargo-test", "macos-filesystem"], required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        raw = sys.stdin.buffer.read(MAX_RAW_SIZE + 1)
        result = execute(raw, args.sha256, args.policy, args.recipe, args.task_id, args.run_id)
        print(canonical(result).decode())
        if result["status"] != "passed":
            raise SystemExit(1)
    except (ValueError, OSError, KeyError) as error:
        print(json.dumps({"status": "error", "code": type(error).__name__}), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
