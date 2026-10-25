"""Peer review unit tests for bounded gateway transport and receiver reconnect."""

import os
import subprocess
import sys
import tempfile
import time
import unittest

from concord_paperclip import policy, store, fixed_command, gateway_transport

BridgeError = policy.BridgeError
canonical = store.canonical
fixed_call = fixed_command.call
exchange = gateway_transport.exchange


def _get_python_executable():
    for candidate in [sys.executable, "/usr/bin/python3", "/bin/python3"]:
        if (
            candidate
            and os.path.isabs(candidate)
            and os.path.isfile(candidate)
            and os.access(candidate, os.X_OK)
        ):
            return candidate
    return sys.executable or "/usr/bin/python3"


def _is_process_running(pid):
    proc_path = f"/proc/{pid}"
    if os.path.exists("/proc"):
        if not os.path.exists(proc_path):
            return False
        try:
            with open(f"{proc_path}/status", "r") as f:
                for line in f:
                    if line.startswith("State:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            # State 'Z' is zombie (terminated/not running)
                            return parts[1] != "Z"
                        break
            return False
        except (FileNotFoundError, ProcessLookupError):
            return False
    else:
        # Fallback for macOS / systems without /proc: bounded ps of exact PID
        try:
            res = subprocess.run(
                ["ps", "-o", "state=", "-p", str(pid)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=2,
            )
            if res.returncode != 0:
                return False
            state = res.stdout.strip()
            return bool(state and not state.startswith("Z"))
        except Exception as exc:
            raise AssertionError("Cannot inspect the exact synthetic child") from exc


class TestGatewayContractValidation(unittest.TestCase):
    """Validation of command argv and credentials parameters."""

    def test_01_command_not_list_or_empty(self):
        for invalid in [None, 123, "echo", (), {}, []]:
            with self.subTest(invalid=invalid):
                with self.assertRaises(BridgeError) as ctx:
                    exchange(invalid, {}, None)
                self.assertEqual(ctx.exception.code, "GATEWAY_NOT_CONFIGURED")

    def test_02_command_empty_arguments(self):
        for cmd in [[""], ["echo", ""], ["", "arg"]]:
            with self.subTest(cmd=cmd):
                with self.assertRaises(BridgeError) as ctx:
                    exchange(cmd, {}, None)
                self.assertEqual(ctx.exception.code, "GATEWAY_NOT_CONFIGURED")

    def test_03_command_non_string_arguments(self):
        for cmd in [[123], ["echo", None], ["tool", True]]:
            with self.subTest(cmd=cmd):
                with self.assertRaises(BridgeError) as ctx:
                    exchange(cmd, {}, None)
                self.assertEqual(ctx.exception.code, "GATEWAY_NOT_CONFIGURED")

    def test_04_command_arguments_with_nul_bytes(self):
        for cmd in [["/bin/echo\0"], ["echo", "hello\0world"]]:
            with self.subTest(cmd=cmd):
                with self.assertRaises(BridgeError) as ctx:
                    exchange(cmd, {}, None)
                self.assertEqual(ctx.exception.code, "GATEWAY_NOT_CONFIGURED")

    def test_05_credentials_required_when_placeholder_present(self):
        cmd = ["/usr/bin/tool", "--auth={credentials}"]
        for cred_dir in [None, "", 123, "/tmp/dir\0evil"]:
            with self.subTest(cred_dir=cred_dir):
                with self.assertRaises(BridgeError) as ctx:
                    exchange(cmd, {}, cred_dir)
                self.assertEqual(ctx.exception.code, "GATEWAY_CREDENTIAL_REQUIRED")

    def test_06_credentials_not_required_when_placeholder_absent(self):
        cmd = ["/bin/echo", "hello"]
        orig_call = gateway_transport.call
        try:
            gateway_transport.call = lambda resolved, req, timeout, limit: {
                "ok": True,
                "result": "success",
            }
            res1 = exchange(cmd, {}, None)
            res2 = exchange(cmd, {}, "")
            self.assertEqual(res1, "success")
            self.assertEqual(res2, "success")
        finally:
            gateway_transport.call = orig_call

    def test_07_credentials_substitution_and_no_mutation(self):
        orig_call = gateway_transport.call
        captured = []
        try:
            gateway_transport.call = lambda resolved, req, timeout, limit: (
                captured.append(resolved) or {"ok": True, "result": "ok"}
            )
            cmd = ["/bin/app", "--cred={credentials}/subpath", "--static"]
            req = {"action": "sync", "payload": [1, 2, 3]}
            cmd_copy = list(cmd)
            req_copy = dict(req)

            result = exchange(cmd, req, "/opt/creds")
            self.assertEqual(result, "ok")
            self.assertEqual(
                captured[0], ["/bin/app", "--cred=/opt/creds/subpath", "--static"]
            )
            # Ensure input argv and request were not mutated
            self.assertEqual(cmd, cmd_copy)
            self.assertEqual(req, req_copy)
        finally:
            gateway_transport.call = orig_call

    def test_08_call_invocation_bounds_and_single_invocation(self):
        orig_call = gateway_transport.call
        calls = []
        try:
            gateway_transport.call = lambda resolved, req, **kwargs: (
                calls.append((resolved, req, kwargs)) or {"ok": True, "result": 42}
            )
            exchange(["/bin/cmd"], {"q": 1}, None)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][2], {"timeout": 110, "limit": 2_000_000})
        finally:
            gateway_transport.call = orig_call


class TestGatewayEnvelopeDecoded(unittest.TestCase):
    """Validation of decoded envelope results, rejection, and error code bounds."""

    def test_09_envelope_not_dict(self):
        orig_call = gateway_transport.call
        try:
            for bad_envelope in [None, [], "not_a_dict", 123]:
                gateway_transport.call = lambda *a, **k: bad_envelope
                with self.subTest(envelope=bad_envelope):
                    with self.assertRaises(BridgeError) as ctx:
                        exchange(["/bin/cmd"], {}, None)
                    self.assertEqual(ctx.exception.code, "GATEWAY_REJECTED")
        finally:
            gateway_transport.call = orig_call

    def test_10_envelope_ok_strict_boolean_type(self):
        orig_call = gateway_transport.call
        try:
            for bad_envelope in [
                {"ok": 1, "result": "val"},
                {"ok": 0, "result": "val"},
                {"ok": "true", "result": "val"},
                {"ok": "false", "result": "val"},
                {"ok": None, "result": "val"},
                {"ok": [], "result": "val"},
                {"result": "val"},  # missing ok
            ]:
                gateway_transport.call = lambda *a, **k: bad_envelope
                with self.subTest(envelope=bad_envelope):
                    with self.assertRaises(BridgeError) as ctx:
                        exchange(["/bin/cmd"], {}, None)
                    self.assertEqual(ctx.exception.code, "GATEWAY_REJECTED")
        finally:
            gateway_transport.call = orig_call

    def test_11_envelope_ok_false_valid_ascii_codes(self):
        orig_call = gateway_transport.call
        try:
            for code in ["GATEWAY_TIMEOUT", "AUTH_FAILED", "A", "A" + "B" * 79, "CODE_123"]:
                gateway_transport.call = lambda *a, **k: {"ok": False, "code": code}
                with self.subTest(code=code):
                    with self.assertRaises(BridgeError) as ctx:
                        exchange(["/bin/cmd"], {}, None)
                    self.assertEqual(ctx.exception.code, code)
        finally:
            gateway_transport.call = orig_call

    def test_12_envelope_ok_false_adversarial_codes(self):
        orig_call = gateway_transport.call
        try:
            for invalid_code in [
                ["UNHASHABLE"],
                {"nested": 1},
                12345,
                None,
                "",
                "lower_case",
                "_START_UNDERSCORE",
                "1START_DIGIT",
                "SPACE CODE",
                "HYPHEN-CODE",
                "NEWLINE\nCODE",
                "CODE\r\n",
                "\u0410UTH",  # Cyrillic capital A (Unicode confusable)
                "A" * 81,     # Exceeds 80 character limit
            ]:
                gateway_transport.call = lambda *a, **k: {"ok": False, "code": invalid_code}
                with self.subTest(code=invalid_code):
                    with self.assertRaises(BridgeError) as ctx:
                        exchange(["/bin/cmd"], {}, None)
                    self.assertEqual(ctx.exception.code, "GATEWAY_REJECTED")
        finally:
            gateway_transport.call = orig_call

    def test_13_envelope_ok_true_result_preserves_falsy_values_and_ignores_metadata(self):
        orig_call = gateway_transport.call
        try:
            for val in [None, False, 0, "", [], {}, {"nested": [1, 2]}]:
                gateway_transport.call = lambda *a, **k: {
                    "ok": True,
                    "result": val,
                    "extra_metadata": "ignored",
                    "trace_id": 9999,
                }
                with self.subTest(val=val):
                    res = exchange(["/bin/cmd"], {}, None)
                    self.assertEqual(res, val)
        finally:
            gateway_transport.call = orig_call

    def test_14_envelope_ok_true_missing_result_key(self):
        orig_call = gateway_transport.call
        try:
            gateway_transport.call = lambda *a, **k: {"ok": True}
            with self.assertRaises(BridgeError) as ctx:
                exchange(["/bin/cmd"], {}, None)
            self.assertEqual(ctx.exception.code, "GATEWAY_UNAVAILABLE")
        finally:
            gateway_transport.call = orig_call

    def test_15_transport_error_secret_suppression_and_no_retry(self):
        orig_call = gateway_transport.call
        call_count = [0]
        secret = "SECRET_NASIK_KEY_VALUE_12345"
        try:
            def failing_call(*a, **k):
                call_count[0] += 1
                raise OSError(f"Connection failure containing {secret}")

            gateway_transport.call = failing_call
            with self.assertRaises(BridgeError) as ctx:
                exchange(["/bin/cmd"], {}, None)

            self.assertEqual(ctx.exception.code, "GATEWAY_UNAVAILABLE")
            self.assertEqual(call_count[0], 1)
            # Ensure raw secret is not echoed in exception message
            self.assertNotIn(secret, str(ctx.exception))
            # Ensure no traceback chaining leaks the inner secret
            self.assertIsNone(ctx.exception.__cause__)
        finally:
            gateway_transport.call = orig_call

    def test_16_system_exit_and_keyboard_interrupt_propagate(self):
        orig_call = gateway_transport.call
        try:
            def raise_interrupt(*a, **k):
                raise KeyboardInterrupt()

            gateway_transport.call = raise_interrupt
            with self.assertRaises(KeyboardInterrupt):
                exchange(["/bin/cmd"], {}, None)

            def raise_exit(*a, **k):
                raise SystemExit(42)

            gateway_transport.call = raise_exit
            with self.assertRaises(SystemExit) as ctx:
                exchange(["/bin/cmd"], {}, None)
            self.assertEqual(ctx.exception.code, 42)
        finally:
            gateway_transport.call = orig_call


class TestRealSubprocessTransport(unittest.TestCase):
    """End-to-end tests invoking real short-lived subprocesses via fixed runner."""

    def setUp(self):
        self.py_exec = _get_python_executable()

    def test_17_real_subprocess_valid_json(self):
        script = (
            "import sys, json\n"
            "_ = sys.stdin.read()\n"
            "sys.stdout.write(json.dumps({'ok': True, 'result': {'status': 'healthy', 'node': 1}}))\n"
        )
        cmd = [self.py_exec, "-c", script]
        res = exchange(cmd, {"query": "ping"}, None)
        self.assertEqual(res, {"status": "healthy", "node": 1})

    def test_18_real_subprocess_invalid_json(self):
        script = (
            "import sys\n"
            "_ = sys.stdin.read()\n"
            "sys.stdout.write('INVALID_NON_JSON{')\n"
        )
        cmd = [self.py_exec, "-c", script]
        with self.assertRaises(BridgeError) as ctx:
            exchange(cmd, {"query": "ping"}, None)
        self.assertEqual(ctx.exception.code, "GATEWAY_UNAVAILABLE")

    def test_19_real_subprocess_nonzero_exit(self):
        script = (
            "import sys\n"
            "_ = sys.stdin.read()\n"
            "sys.stdout.write('{\"ok\": true, \"result\": 1}')\n"
            "sys.exit(2)\n"
        )
        cmd = [self.py_exec, "-c", script]
        with self.assertRaises(BridgeError) as ctx:
            exchange(cmd, {"query": "ping"}, None)
        self.assertEqual(ctx.exception.code, "GATEWAY_UNAVAILABLE")

    def test_20_real_subprocess_output_exceeding_limit(self):
        # Generates > 2MB output to trigger limit cutoff
        script = (
            "import sys\n"
            "_ = sys.stdin.read()\n"
            "chunk = 'X' * 65536\n"
            "for _ in range(32):\n"
            "    sys.stdout.write(chunk)\n"
            "sys.stdout.flush()\n"
        )
        cmd = [self.py_exec, "-c", script]
        with self.assertRaises(BridgeError) as ctx:
            exchange(cmd, {"query": "big"}, None)
        self.assertEqual(ctx.exception.code, "GATEWAY_UNAVAILABLE")

    def test_21_real_subprocess_link_loss_regressions(self):
        # Scenario A: Child terminated by SIGTERM (link severed abruptly)
        script_term = (
            "import os, signal, sys\n"
            "_ = sys.stdin.read()\n"
            "os.kill(os.getpid(), signal.SIGTERM)\n"
        )
        with self.assertRaises(BridgeError) as ctx:
            exchange([self.py_exec, "-c", script_term], {"link": "test"}, None)
        self.assertEqual(ctx.exception.code, "GATEWAY_UNAVAILABLE")

        # Scenario B: Transport error / SSH connection refused returncode (255)
        script_conn_refused = (
            "import sys\n"
            "_ = sys.stdin.read()\n"
            "sys.stderr.write('ssh: connect to host port 22: Connection refused\\n')\n"
            "sys.exit(255)\n"
        )
        with self.assertRaises(BridgeError) as ctx:
            exchange([self.py_exec, "-c", script_conn_refused], {"link": "test"}, None)
        self.assertEqual(ctx.exception.code, "GATEWAY_UNAVAILABLE")

        # Scenario C: Broken stream mid-envelope
        script_truncated = (
            "import sys\n"
            "_ = sys.stdin.read()\n"
            "sys.stdout.write('{\"ok\": true, \"res')\n"
            "sys.stdout.flush()\n"
            "sys.exit(0)\n"
        )
        with self.assertRaises(BridgeError) as ctx:
            exchange([self.py_exec, "-c", script_truncated], {"link": "test"}, None)
        self.assertEqual(ctx.exception.code, "GATEWAY_UNAVAILABLE")

    def test_22_real_subprocess_descendant_cleanup_on_timeout(self):
        if not hasattr(os, "fork"):
            self.skipTest("os.fork not available on this platform")

        with tempfile.TemporaryDirectory() as scratch_dir:
            pid_file = os.path.join(scratch_dir, "grandchild.pid")

            # Synthetic child reads stdin, forks one child retaining stdout for at most 5s,
            # writes its PID into a temporary scratch file, then sleeps.
            script = (
                "import os, sys, time\n"
                "pid_file = sys.argv[1]\n"
                "sys.stdin.read()\n"
                "pid = os.fork()\n"
                "if pid == 0:\n"
                "    try:\n"
                "        with open(pid_file, 'w') as f:\n"
                "            f.write(str(os.getpid()))\n"
                "            f.flush()\n"
                "    except Exception:\n"
                "        pass\n"
                "    time.sleep(5)\n"
                "    sys.exit(0)\n"
                "else:\n"
                "    time.sleep(5)\n"
                "    sys.exit(0)\n"
            )

            orig_call = gateway_transport.call
            try:
                # Wrap original fixed runner with timeout=0.25s for fast execution
                def fast_call(cmd, req, timeout=110, limit=2_000_000):
                    return fixed_call(cmd, req, timeout=0.25, limit=limit)

                gateway_transport.call = fast_call

                with self.assertRaises(BridgeError) as ctx:
                    exchange([self.py_exec, "-c", script, pid_file], {"x": 1}, None)
                self.assertEqual(ctx.exception.code, "GATEWAY_UNAVAILABLE")
            finally:
                gateway_transport.call = orig_call

            # Read grandchild PID recorded in scratch file
            grandchild_pid = None
            start_wait = time.monotonic()
            while time.monotonic() - start_wait < 1.0:
                if os.path.exists(pid_file):
                    try:
                        with open(pid_file, "r") as f:
                            content = f.read().strip()
                            if content:
                                grandchild_pid = int(content)
                                break
                    except Exception:
                        pass
                time.sleep(0.02)

            self.assertIsNotNone(
                grandchild_pid, "Grandchild PID scratch file was not written"
            )

            # Assert cleanup completes promptly and child is absent or zombie (not running)
            deadline = time.monotonic() + 1.0
            running = True
            while time.monotonic() < deadline:
                if not _is_process_running(grandchild_pid):
                    running = False
                    break
                time.sleep(0.05)

            self.assertFalse(
                running,
                f"Descendant grandchild PID {grandchild_pid} was still running after process-group cleanup",
            )


if __name__ == "__main__":
    unittest.main()
