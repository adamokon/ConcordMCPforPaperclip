import hashlib
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

import pytest

from concord_paperclip.bounded_process import ProcessPolicyError, run_bounded


def run(code, **kwargs):
    with tempfile.TemporaryDirectory() as directory:
        return run_bounded([sys.executable, "-c", code], str(Path(directory).resolve()),
                           {"PATH": "/usr/bin:/bin"}, **kwargs)


def test_exit_and_hash():
    result = run("print('ok')")
    assert result["status"] == "passed" and result["output"] == b"ok\n"
    assert result["output_sha256"] == hashlib.sha256(b"ok\n").hexdigest()
    assert run("print('PASS'); raise SystemExit(2)")["status"] == "failed"


def test_clean_environment():
    with patch.dict(os.environ, {"UNEXPECTED_SENTINEL": "synthetic"}):
        assert run("import os; print(os.getenv('UNEXPECTED_SENTINEL'))")["output"] == b"None\n"


def test_output_bound():
    result = run("import sys; sys.stdout.write('x'*100000)", max_output=64)
    assert result["status"] == "output_limit" and result["truncated"]
    assert result["output"] == b"x" * 64
    assert run("import sys; sys.stdout.write('x'*64)", max_output=64)["status"] == "passed"


def test_timeout_and_parent_exited_child_holding_pipe():
    start = time.monotonic()
    result = run("import time; time.sleep(30)", timeout=0.2)
    assert result["status"] == "timeout" and time.monotonic() - start < 3
    if hasattr(os, "fork"):
        code = "import os,time; pid=os.fork(); os._exit(0) if pid else time.sleep(30)"
        assert run(code, timeout=0.2)["status"] == "timeout"


@pytest.mark.parametrize("value", [True, float('nan'), float('inf'), 0, -1, 1801])
def test_bad_timeout(value):
    with pytest.raises(ProcessPolicyError):
        run("pass", timeout=value)


def test_root_guard_and_hard_limits():
    with patch("concord_paperclip.bounded_process.os.geteuid", return_value=0):
        with pytest.raises(ProcessPolicyError):
            run("pass")
    code = "import resource; a,b=resource.getrlimit(resource.RLIMIT_CORE); print(a,b)"
    assert run(code)["output"] == b"0 0\n"


def test_selector_creation_failure_cleans_child():
    import subprocess
    from concord_paperclip import bounded_process
    children = []
    original = subprocess.Popen
    def capture(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child
    with patch.object(bounded_process.subprocess, "Popen", side_effect=capture):
        with patch.object(bounded_process.selectors, "DefaultSelector", side_effect=RuntimeError("synthetic")):
            with pytest.raises(RuntimeError):
                run("import time; time.sleep(30)")
    assert children and children[0].poll() is not None
