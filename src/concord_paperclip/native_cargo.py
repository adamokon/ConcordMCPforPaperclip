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
from .native_profile import environment, profile, validate_path
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
    if type(policy) is not dict or not keys <= set(policy) or set(policy) - keys - {"dependencies", "package", "no_default_features"}:
        raise NativeExecutionError("Invalid policy schema")
    if "no_default_features" in policy and type(policy["no_default_features"]) is not bool:
        raise NativeExecutionError("Invalid operator feature policy")
    if "package" in policy and (not isinstance(policy["package"], str) or
                                not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", policy["package"])):
        raise NativeExecutionError("Invalid operator Cargo package")
    if "dependencies" in policy:
        dependency = policy["dependencies"]
        if type(dependency) is not dict or not {"path", "sha256"} <= set(dependency) or set(dependency) - {"path", "sha256", "native"}:
            raise NativeExecutionError("Invalid dependency closure")
        if "native" in dependency and type(dependency["native"]) is not bool:
            raise NativeExecutionError("Invalid native library policy")
        validate_path(dependency["path"])
        if type(dependency["sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", dependency["sha256"]):
            raise NativeExecutionError("Invalid dependency manifest digest")
        cache = _root_path(dependency["path"])
        _root_path(str(cache / "vendor"))
        manifest = _root_path(str(cache / "manifest.json"), directory=False)
        if hashlib.sha256(manifest.read_bytes()).hexdigest() != dependency["sha256"]:
            raise NativeExecutionError("Dependency manifest digest mismatch")
        if dependency.get("native"):
            for relative in ("native/openssl", "native/zstd", "native/pkgconfig"):
                _root_path(str(cache / relative))
            _root_path(str(cache / "native/bin/pkg-config"), directory=False)
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


def _fixture_recipe(toolchain, source, recipe, package=None, no_default_features=False):
    argv = [str(toolchain / "bin" / "cargo")]
    if recipe == "cargo-check":
        argv += ["check"]
    elif recipe == "cargo-build":
        if package is None:
            raise NativeExecutionError("Build recipe requires an operator-selected package")
        argv += ["build", "--bin", package]
    elif recipe in ("cargo-test", "macos-filesystem"):
        argv += ["test"]
    else:
        raise NativeExecutionError("Unknown fixed recipe")
    argv += ["--offline", "--locked", "--manifest-path", str(source / "Cargo.toml")]
    if package is not None:
        argv += ["--package", package]
    if no_default_features:
        argv += ["--no-default-features"]
    if recipe == "macos-filesystem":
        argv += ["--test", "macos_filesystem"]
    return argv



def _retain_binary(directory, job, name):
    """Copy a bounded regular Mach-O only after all build-UID processes stop."""
    target = os.open(directory.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parent = os.open(directory.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=target)
    finally:
        os.close(target)
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    finally:
        os.close(parent)
    with os.fdopen(descriptor, "rb") as source:
        metadata = os.fstat(source.fileno())
        if not stat.S_ISREG(metadata.st_mode) or not 4 <= metadata.st_size <= 512 * 1024 * 1024:
            raise NativeExecutionError("Invalid build artifact type or size")
        magic = source.read(4)
        if magic not in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf"):
            raise NativeExecutionError("Build artifact must be a native Mach-O executable")
        output = job / "artifact"
        digest = hashlib.sha256()
        with output.open("xb") as destination:
            destination.write(magic)
            digest.update(magic)
            remaining = metadata.st_size - 4
            while remaining:
                chunk = source.read(min(remaining, 1024 * 1024))
                if not chunk:
                    raise NativeExecutionError("Build artifact truncated")
                digest.update(chunk)
                destination.write(chunk)
                remaining -= len(chunk)
            if source.read(1):
                raise NativeExecutionError("Build artifact grew")
        output.chmod(0o500)
        return dict(name=name, path=str(output), size=metadata.st_size, sha256=digest.hexdigest())

def execute(raw, digest, policy_path, recipe, task_id, run_id):
    if os.geteuid() != 0:
        raise NativeExecutionError("Trusted root launcher required to drop build identity")
    if not shutil.rmtree.avoids_symlink_attacks:
        raise NativeExecutionError("Symlink-safe workspace cleanup unavailable")
    code_hashes = {name: hashlib.sha256(Path(__file__).with_name(name + ".py").read_bytes()).hexdigest()
                   for name in ("native_cargo", "native_profile", "bounded_process", "source_snapshot")}
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
        if "dependencies" in policy:
            cache = policy["dependencies"]["path"]
            sb += f"(allow file-read* (subpath {json.dumps(cache)}))\n"
            config = ('[source.crates-io]\nreplace-with = "operator-vendor"\n'
                      '[source.operator-vendor]\ndirectory = ' + json.dumps(cache + "/vendor") + '\n')
            config_path = workspace / "cargo-home" / "config.toml"
            config_path.write_text(config)
            config_path.chmod(0o644)
            if policy["dependencies"].get("native"):
                env.update(OPENSSL_DIR=cache + "/native/openssl", OPENSSL_STATIC="1",
                           PKG_CONFIG=cache + "/native/bin/pkg-config", PKG_CONFIG_ALL_STATIC="1",
                           PKG_CONFIG_LIBDIR=cache + "/native/pkgconfig", ZSTD_SYS_USE_PKG_CONFIG="1")
        sandbox = job / "sandbox.sb"
        sandbox.write_text(sb)
        sandbox.chmod(0o644)
        argv = ["/usr/bin/sandbox-exec", "-f", str(sandbox)] + _fixture_recipe(
            Path(policy["toolchain"]), source, recipe, policy.get("package"), policy.get("no_default_features", False))
        artifact = None
        try:
            result = run_bounded(argv, str(workspace), env, policy["timeout"], policy["max_output"],
                                 uid=policy["uid"], gid=policy["gid"])
            if recipe == "cargo-build" and result["status"] == "passed":
                _cleanup_uid(policy["uid"])
                artifact = _retain_binary(workspace / "target" / "debug", job, policy["package"])
        finally:
            _cleanup_uid(policy["uid"])
            shutil.rmtree(workspace)
            shutil.rmtree(source)
        # The receipt is written by root outside the builder's writable sandbox.
        output = result.pop("output")
        (job / "output.log").write_bytes(output)
        receipt = dict(schema_version=1, task_id=task_id, run_id=run_id, commit=snapshot["commit"],
                       source_sha256=digest, policy_sha256=policy_hash, recipe=recipe,
                       package=policy.get("package"), no_default_features=policy.get("no_default_features", False),
                       execution_target=policy["target"], build_uid=policy["uid"],
                       credential_free=True, network="deny-all", input_readonly=True,
                       environment_removed=True, **result)
        if artifact is not None:
            receipt["artifact"] = artifact
        receipt["system_services_exempted"] = _uid_inventory(policy["uid"])[1]
        receipt["executor_files_sha256"] = code_hashes
        if "dependencies" in policy:
            receipt["dependencies_sha256"] = policy["dependencies"]["sha256"]
        receipt["toolchain_sha256"] = {name: hashlib.sha256((Path(policy["toolchain"]) / "bin" / name).read_bytes()).hexdigest()
                                       for name in ("cargo", "rustc", "rustdoc")}
        (job / "receipt.json").write_bytes(canonical(receipt) + b"\n")
        return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--recipe", choices=["cargo-check", "cargo-test", "macos-filesystem", "cargo-build"], required=True)
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
