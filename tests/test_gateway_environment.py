"""Receiver boundary tests using Antigravity's isolated synthetic package."""
import copy
import os
import unittest
from unittest.mock import patch

from concord_paperclip import automation, gateway_transport
from concord_paperclip.policy import BridgeError


class TestGatewayEnvironment(unittest.TestCase):
    def test_trusted_environment_is_passed_to_exchange(self):
        command = ["/trusted/tool", "{credentials}/auth"]
        request = {"CREDENTIALS_DIRECTORY": "/untrusted/request"}
        with patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": "/trusted/credentials"}, clear=True):
            with patch.object(gateway_transport, "exchange", return_value="accepted") as exchange:
                self.assertEqual(automation.gateway({"gateway_command": command}, request), "accepted")
        exchange.assert_called_once_with(command, request, "/trusted/credentials")

    def test_absent_environment_without_placeholder_is_valid(self):
        request = {"action": "read"}
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(gateway_transport, "call", return_value={"ok": True, "result": "ready"}) as call:
                self.assertEqual(automation.gateway({"gateway_command": ["/trusted/tool"]}, request), "ready")
        call.assert_called_once_with(["/trusted/tool"], request, timeout=110, limit=2_000_000)

    def test_missing_credentials_fail_before_process(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(gateway_transport, "call") as call, patch("subprocess.Popen") as popen:
                with self.assertRaises(BridgeError) as caught:
                    automation.gateway({"gateway_command": ["/trusted/tool", "{credentials}/auth"]}, {})
        self.assertEqual(caught.exception.code, "GATEWAY_CREDENTIAL_REQUIRED")
        call.assert_not_called()
        popen.assert_not_called()

    def test_request_command_stays_data_and_inputs_are_unchanged(self):
        command = ["/trusted/tool", "--auth={credentials}/auth"]
        config = {"gateway_command": command}
        request = {"gateway_command": ["/malicious/tool"], "payload": {"values": [1, 2]}}
        before = copy.deepcopy((config, request))
        with patch.dict(os.environ, {"CREDENTIALS_DIRECTORY": "/trusted/credentials"}, clear=True):
            with patch.object(gateway_transport, "call", return_value={"ok": True, "result": "ok"}) as call:
                self.assertEqual(automation.gateway(config, request), "ok")
        call.assert_called_once_with(["/trusted/tool", "--auth=/trusted/credentials/auth"], request,
                                     timeout=110, limit=2_000_000)
        self.assertIs(call.call_args.args[1], request)
        self.assertIsNot(call.call_args.args[0], command)
        self.assertEqual((config, request), before)

    def test_actual_falsy_results_preserve_type_and_value(self):
        for value in (None, False, 0):
            with self.subTest(value=value), patch.dict(os.environ, {}, clear=True):
                with patch.object(gateway_transport, "call", return_value={"ok": True, "result": value}) as call:
                    result = automation.gateway({"gateway_command": ["/trusted/tool"]}, {})
                self.assertEqual(result, value)
                self.assertIs(type(result), type(value))
                call.assert_called_once_with(["/trusted/tool"], {}, timeout=110, limit=2_000_000)

    def test_rejections_and_transport_failure_are_not_retried(self):
        cases = (({"ok": False, "code": "AUTH_DENIED"}, "AUTH_DENIED"),
                 ({"ok": False, "code": "bad code"}, "GATEWAY_REJECTED"),
                 (OSError("synthetic failure"), "GATEWAY_UNAVAILABLE"))
        for outcome, expected in cases:
            with self.subTest(expected=expected), patch.dict(os.environ, {}, clear=True):
                config = {"gateway_command": ["/trusted/tool"]}
                request = {"payload": [1]}
                before = copy.deepcopy((config, request))
                options = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
                with patch.object(gateway_transport, "call", **options) as call:
                    with self.assertRaises(BridgeError) as caught:
                        automation.gateway(config, request)
                self.assertEqual(caught.exception.code, expected)
                call.assert_called_once_with(["/trusted/tool"], request, timeout=110, limit=2_000_000)
                self.assertEqual((config, request), before)


if __name__ == "__main__":
    unittest.main()
