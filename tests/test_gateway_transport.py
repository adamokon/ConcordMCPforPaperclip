"""Public contract tests; no real runner, configuration or credentials."""

import copy
import importlib.util
from pathlib import Path
from concord_paperclip import gateway_transport as installed_transport
import subprocess
import sys
import types
import unittest
from unittest.mock import Mock


class BridgeError(Exception):
    pass


def load_transport():
    name = "_gateway_contract_fixture"
    package = types.ModuleType(name)
    package.__path__ = []
    fixed = types.ModuleType(name + ".fixed_command")
    fixed.call = Mock()
    policy = types.ModuleType(name + ".policy")
    policy.BridgeError = BridgeError
    modules = {name: package, fixed.__name__: fixed, policy.__name__: policy}
    previous = {key: sys.modules.get(key) for key in modules}
    sys.modules.update(modules)
    try:
        spec = importlib.util.spec_from_file_location(
            name + ".gateway_transport", Path(installed_transport.__file__))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for key, value in previous.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value


gateway = load_transport()


class TransportTests(unittest.TestCase):
    def setUp(self):
        gateway.call = Mock(return_value={"ok": True, "result": "accepted"})

    def assert_code(self, code, command=None, request=None, directory=""):
        with self.assertRaises(BridgeError) as caught:
            gateway.exchange(["receiver"] if command is None else command,
                             request, directory)
        self.assertEqual(caught.exception.args, (code,))
        self.assertEqual(str(caught.exception), code)
        self.assertTrue(caught.exception.__suppress_context__ or
                        caught.exception.__context__ is None)

    def test_success_exact_runner_contract_and_no_mutation(self):
        command = ["receiver", "literal space", "$(echo private); > /tmp/x"]
        request = {"nested": [1, {"value": "synthetic-secret"}]}
        before_command, before_request = copy.deepcopy((command, request))
        self.assertEqual(gateway.exchange(command, request, ""), "accepted")
        gateway.call.assert_called_once_with(command, request, timeout=110, limit=2000000)
        self.assertIsNot(gateway.call.call_args.args[0], command)
        self.assertIs(gateway.call.call_args.args[1], request)
        self.assertEqual(command, before_command)
        self.assertEqual(request, before_request)

    def test_results_are_returned_unchanged(self):
        for result in (None, False, 0, "", [], {}, {"x": [1]}):
            with self.subTest(result=result):
                gateway.call.return_value = {"ok": True, "result": result,
                                             "code": ["ignored"], "extra": "ignored"}
                self.assertIs(gateway.exchange(["receiver"], {}, ""), result)

    def test_invalid_commands_never_launch(self):
        for command in (None, "receiver", (), {}, [], [""], ["a", ""],
                        [1], [False], [None], ["a\0b"], ["a", []]):
            with self.subTest(command=command):
                # None is the helper default, so call directly here.
                with self.assertRaises(BridgeError) as caught:
                    gateway.exchange(command, {}, "")
                self.assertEqual(caught.exception.args, ("GATEWAY_NOT_CONFIGURED",))
        gateway.call.assert_not_called()

    def test_command_validation_precedes_credentials(self):
        self.assert_code("GATEWAY_NOT_CONFIGURED", ["{credentials}", ""], directory=None)
        gateway.call.assert_not_called()

    def test_credentials_required_before_launch(self):
        for directory in (None, "", 0, False, [], {}, b"path", "bad\0path"):
            with self.subTest(directory=directory):
                self.assert_code("GATEWAY_CREDENTIAL_REQUIRED", ["{credentials}/key"],
                                 directory=directory)
        gateway.call.assert_not_called()

    def test_literal_substitution_and_preservation(self):
        command = ["receiver", "--key={credentials}/key", "{credentials}{credentials}",
                   "{credential}", "$(literal); spaces"]
        before = command[:]
        directory = "/synthetic path/$(literal)"
        gateway.exchange(command, {}, directory)
        gateway.call.assert_called_once_with(
            ["receiver", "--key=" + directory + "/key", directory + directory,
             "{credential}", "$(literal); spaces"], {}, timeout=110, limit=2000000)
        self.assertEqual(command, before)

    def test_unused_credentials_not_required_or_interpreted(self):
        for directory in (None, [], "bad\0path", "{credentials}"):
            gateway.exchange(["receiver"], {}, directory)
        self.assertEqual(gateway.call.call_count, 4)

    def test_replacement_is_not_recursive(self):
        gateway.exchange(["receiver", "{credentials}"], {}, "/{credentials}")
        self.assertEqual(gateway.call.call_args.args[0], ["receiver", "/{credentials}"])

    def test_runner_failures_are_sanitized_once(self):
        failures = [BridgeError("FIXED_COMMAND_TIMEOUT"),
                    BridgeError("FIXED_COMMAND_FAILED"),
                    BridgeError("FIXED_COMMAND_INPUT_LIMIT"),
                    BridgeError("FIXED_COMMAND_OUTPUT_LIMIT"),
                    ValueError("synthetic-secret invalid JSON"),
                    BrokenPipeError("synthetic-secret pipe"),
                    OSError("synthetic-secret startup"),
                    subprocess.TimeoutExpired("synthetic-secret", 110),
                    TypeError("synthetic-secret serialization"),
                    RecursionError("synthetic-secret serialization"),
                    RuntimeError("synthetic-secret unexpected runner failure")]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                gateway.call = Mock(side_effect=failure)
                self.assert_code("GATEWAY_UNAVAILABLE", ["receiver", "{credentials}"],
                                 request={"secret": "synthetic-secret"},
                                 directory="/synthetic-secret")
                self.assertEqual(gateway.call.call_count, 1)
                self.assertEqual(gateway.call.call_args.kwargs,
                                 {"timeout": 110, "limit": 2000000})

    def test_process_control_exceptions_propagate(self):
        for failure in (KeyboardInterrupt(), SystemExit(3)):
            gateway.call = Mock(side_effect=failure)
            with self.assertRaises(type(failure)):
                gateway.exchange(["receiver"], {}, "")
            gateway.call.assert_called_once()

    def test_non_dict_envelopes_rejected(self):
        for envelope in (None, False, 0, [], ["ok"], "bad JSON", "x" * 2000001):
            gateway.call.return_value = envelope
            self.assert_code("GATEWAY_REJECTED")

    def test_missing_or_nonboolean_ok_does_not_trust_code(self):
        for envelope in ({}, {"code": "TRUST_ME"}, *(
                {"ok": value, "code": "TRUST_ME", "result": 42}
                for value in (None, 0, 1, "true", "false", [], {}))):
            gateway.call.return_value = envelope
            self.assert_code("GATEWAY_REJECTED")

    def test_success_missing_result_is_unavailable(self):
        gateway.call.return_value = {"ok": True, "code": "TRUST_ME"}
        self.assert_code("GATEWAY_UNAVAILABLE")

    def test_valid_rejection_codes(self):
        for code in ("A", "ERROR_12", "A" + "9_" * 39 + "Z"):
            gateway.call.return_value = {"ok": False, "code": code, "result": 42}
            self.assert_code(code)

    def test_invalid_rejection_codes_safely_rejected(self):
        for code in (None, False, 0, [], {}, ["ERROR"], {"code": "ERROR"},
                     "", "lower", "A-b", "_ERROR", "1ERROR", "A\n", "A\0B",
                     "ÉRROR", "A１", "A" * 81, "synthetic-secret/path"):
            gateway.call.return_value = {"ok": False, "code": code}
            self.assert_code("GATEWAY_REJECTED")
        gateway.call.return_value = {"ok": False}
        self.assert_code("GATEWAY_REJECTED")

    def test_large_result_is_not_reencoded(self):
        result = {"payload": "x" * 2000000}
        gateway.call.return_value = {"ok": True, "result": result}
        self.assertIs(gateway.exchange(["receiver"], {}, ""), result)
        gateway.call.assert_called_once()


if __name__ == "__main__":
    unittest.main()
