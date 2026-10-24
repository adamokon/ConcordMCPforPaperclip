"""Bounded execution of operator-selected commands; never expose argv through MCP."""

import hashlib
import math
import os
import resource
import selectors
import signal
import subprocess
import time

class ProcessPolicyError(ValueError):
    pass

def _clamp(res, val):
    soft, hard = resource.getrlimit(res)
    bounds = [val] + [x for x in (soft, hard) if x != resource.RLIM_INFINITY]
    target = min(bounds)
    resource.setrlimit(res, (target, target))

def _kill_group(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        proc.kill()
    except OSError:
        pass

def run_bounded(argv, cwd, env, timeout=60.0, max_output=1048576, uid=None, gid=None) -> dict:
    if not isinstance(argv, list) or not (1 <= len(argv) <= 128) or not all(
        isinstance(a, str) and len(a) <= 4096 and '\0' not in a for a in argv
    ) or not os.path.isabs(argv[0]):
        raise ProcessPolicyError("Invalid argv")
    if (not isinstance(cwd, str) or '\0' in cwd or not os.path.isabs(cwd)
            or not os.path.isdir(cwd) or os.path.realpath(cwd) != cwd):
        raise ProcessPolicyError("Invalid cwd")
    if not isinstance(env, dict) or len(env) > 32 or not all(
        isinstance(k, str) and isinstance(v, str) and '\0' not in k and '\0' not in v for k, v in env.items()
    ):
        raise ProcessPolicyError("Invalid env")
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not (0 < timeout <= 1800):
        raise ProcessPolicyError("Invalid timeout")
    if type(max_output) is not int or not (1 <= max_output <= 4194304):
        raise ProcessPolicyError("Invalid max_output")
    if (uid is None) != (gid is None):
        raise ProcessPolicyError("uid and gid must both be set or both None")
    if uid is not None and (type(uid) is not int or type(gid) is not int or uid <= 0 or gid <= 0):
        raise ProcessPolicyError("uid and gid must be positive ints")
    euid = os.geteuid()
    if euid == 0:
        if uid is None:
            raise ProcessPolicyError("Explicit non-root uid/gid required when running as root")
    elif uid is not None and (uid != euid or gid != os.getegid()):
        raise ProcessPolicyError("Nonroot identities must match current effective identities")

    def _preexec():
        _clamp(resource.RLIMIT_CORE, 0)
        _clamp(resource.RLIMIT_NOFILE, 512)
        _clamp(resource.RLIMIT_CPU, math.ceil(timeout) + 2)
        _clamp(resource.RLIMIT_FSIZE, 512 * 1024 * 1024)
        if uid is not None and hasattr(resource, "RLIMIT_NPROC"):
            _clamp(resource.RLIMIT_NPROC, 64)

    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "start_new_session": True,
        "close_fds": True,
        "cwd": cwd,
        "env": env,
        "preexec_fn": _preexec,
    }
    if euid == 0:
        kwargs.update(user=uid, group=gid, extra_groups=[])

    start_time = time.monotonic()
    deadline = start_time + timeout
    output = bytearray()
    truncated = False
    status = None

    proc = subprocess.Popen(argv, **kwargs)
    sel = None
    try:
        sel = selectors.DefaultSelector()
        os.set_blocking(proc.stdout.fileno(), False)
        sel.register(proc.stdout, selectors.EVENT_READ)
        while True:
            rem = deadline - time.monotonic()
            if rem <= 0:
                status = "timeout"
                _kill_group(proc)
                break
            events = sel.select(timeout=rem)
            if not events:
                if time.monotonic() >= deadline:
                    status = "timeout"
                    _kill_group(proc)
                    break
                continue
            try:
                chunk = os.read(proc.stdout.fileno(), 65536)
            except (BlockingIOError, InterruptedError):
                continue
            if not chunk:
                break
            if len(output) + len(chunk) > max_output:
                output.extend(chunk[: max_output - len(output)])
                truncated = True
                status = "output_limit"
                _kill_group(proc)
                break
            output.extend(chunk)

        rem = max(0.0, deadline - time.monotonic())
        try:
            proc.wait(timeout=rem if status is None else 1.0)
        except subprocess.TimeoutExpired:
            if status is None:
                status = "timeout"
            _kill_group(proc)
            try:
                proc.wait(timeout=1.0)
            except Exception:
                pass
    except BaseException:
        _kill_group(proc)
        try:
            proc.wait(timeout=1.0)
        except Exception:
            pass
        raise
    finally:
        try:
            if sel is not None:
                sel.close()
        except Exception:
            pass
        if proc.stdout:
            try:
                proc.stdout.close()
            except Exception:
                pass

    code = proc.returncode if proc.returncode is not None else -signal.SIGKILL
    if status is None:
        status = "passed" if code == 0 else "failed"

    out_bytes = bytes(output)
    return {
        "status": status,
        "exit_code": code,
        "output": out_bytes,
        "output_sha256": hashlib.sha256(out_bytes).hexdigest(),
        "duration_seconds": time.monotonic() - start_time,
        "truncated": truncated,
    }
