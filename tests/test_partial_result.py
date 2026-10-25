import copy
import unittest
from concord_paperclip.partial_result import classify_partial, validate_partial_record

RUN = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def facts():
    return dict(
        run_id=RUN,
        expected_run_id=RUN,
        worker_status="error",
        worker_exit_code=1,
        worker_denied_actions=[],
        elapsed_seconds=484,
        deadline_seconds=480,
        timeout_observed=True,
        provider_stopped=True,
        environment_removed=True,
        auth_error=False,
        quota_error=False,
        security_error=False,
        producer_verified=True,
        task_cancelled=False,
        file_count=2,
        allowed_scope=True,
        cli_status="SUCCESS",
        cli_response_empty=True,
        outer_timeout=False,
        native_status="failed",
    )


def expected():
    return dict(
        task_id=RUN,
        issue_id=OTHER,
        run_id=RUN,
        agent_id=OTHER,
        paths=["partial_result.py", "test_partial_result.py", "RESULT.txt"],
    )


def record():
    e = expected()
    return dict(
        schema_version=1,
        kind="partial",
        reason="final_response_timeout",
        complete=False,
        binding={k: e[k] for k in ("task_id", "issue_id", "run_id", "agent_id")},
        snapshot_digest="a0" * 32,
        present_paths=["partial_result.py"],
        missing_paths=["test_partial_result.py", "RESULT.txt"],
    )


class ClassificationTests(unittest.TestCase):
    def assertEligible(self, f, eligible):
        result = classify_partial(f)
        self.assertEqual(set(result), {"eligible", "code"})
        self.assertIs(result["eligible"], eligible)
        self.assertRegex(result["code"], r"^[a-z0-9_]+$")

    def test_observed_deadline_boundary(self):
        for elapsed, eligible in [(484, True), (480, True), (479.9, False)]:
            with self.subTest(elapsed=elapsed):
                self.assertEligible(dict(facts(), elapsed_seconds=elapsed), eligible)

    def test_cancelled_task_read_only_harvest(self):
        result = classify_partial(dict(facts(), task_cancelled=True))
        self.assertEqual(result, {"eligible": True, "code": "partial_final_response_timeout"})
        self.assertNotIn("retry", result)
        self.assertNotIn("reopen", result)

    def test_outer_timeout_and_native_status(self):
        self.assertEligible(dict(facts(), cli_status=None, outer_timeout=True), True)
        self.assertEligible(dict(facts(), native_status="succeeded"), True)
        for status in ["cancelled", "running", "unknown", None, [], True]:
            with self.subTest(status=status):
                self.assertEligible(dict(facts(), native_status=status), False)
        self.assertEligible(dict(facts(), cli_status=None), False)
        for status in ["ERROR", "success", "", [], True]:
            self.assertEligible(dict(facts(), cli_status=status, outer_timeout=True), False)

    def test_each_required_proof_missing(self):
        for key in facts():
            f = facts()
            del f[key]
            with self.subTest(key=key):
                self.assertEligible(f, False)

    def test_flags_strict_and_cleanup_idle(self):
        for key in [
            "timeout_observed",
            "provider_stopped",
            "environment_removed",
            "producer_verified",
            "allowed_scope",
            "cli_response_empty",
        ]:
            for value in [False, 1, "true", None, [], {}]:
                with self.subTest(key=key, value=value):
                    self.assertEligible(dict(facts(), **{key: value}), False)
        for key in ["auth_error", "quota_error", "security_error"]:
            for value in [True, 0, None, "false", []]:
                self.assertEligible(dict(facts(), **{key: value}), False)
        for key in ["outer_timeout", "task_cancelled"]:
            for value in [0, 1, "false", None, []]:
                self.assertEligible(dict(facts(), **{key: value}), False)

    def test_binding_worker_count_and_numbers(self):
        for key, values in {
            "run_id": [RUN.upper(), OTHER, "", None, [], RUN + "\n"],
            "expected_run_id": [OTHER, RUN.upper(), None],
            "worker_status": ["SUCCESS", "running", None, []],
            "worker_exit_code": [True, 1.0, 0, 2, 10**1000],
            "worker_denied_actions": [(), None, ["denied"], {}],
            "file_count": [True, 0, 129, 1.0, 10**1000],
            "elapsed_seconds": [
                -1,
                True,
                "484",
                None,
                [],
                float("nan"),
                float("inf"),
                -float("inf"),
                10**1000,
                1e300,
            ],
            "deadline_seconds": [0, 0.9, True, None, float("nan"), float("inf"), 10**1000],
        }.items():
            for value in values:
                with self.subTest(key=key, value_type=type(value).__name__):
                    self.assertEligible(dict(facts(), **{key: value}), False)
        for count in [1, 128]:
            self.assertEligible(dict(facts(), file_count=count), True)

    def test_malformed_and_immutable(self):
        for malformed in [None, [], True, "facts"]:
            self.assertEligible(malformed, False)
        f = facts()
        before = copy.deepcopy(f)
        classify_partial(f)
        self.assertEqual(f, before)


class RecordTests(unittest.TestCase):
    def test_valid_partition_and_immutable(self):
        r, e = record(), expected()
        before = copy.deepcopy((r, e))
        e["trusted_extra"] = "allowed"
        self.assertTrue(validate_partial_record(r, e))
        del e["trusted_extra"]
        self.assertEqual((r, e), before)
        r["present_paths"] = e["paths"][:]
        r["missing_paths"] = []
        self.assertTrue(validate_partial_record(r, e))

    def test_exact_fields_and_types(self):
        for key in record():
            r = record()
            del r[key]
            self.assertFalse(validate_partial_record(r, expected()))
        r = record()
        r["secret"] = "unexpected"
        self.assertFalse(validate_partial_record(r, expected()))
        for key, values in {
            "schema_version": [True, 1.0, "1", 2, []],
            "kind": ["complete", [], True],
            "reason": ["timeout", [], None],
            "complete": [0, None, "false", True],
            "snapshot_digest": ["A" * 64, "a" * 63, "g" * 64, "a" * 64 + "\n", [], None],
            "binding": [[], None, {}],
        }.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    r = record()
                    r[key] = value
                    self.assertFalse(validate_partial_record(r, expected()))

    def test_binding_exact(self):
        for key in ("task_id", "issue_id", "run_id", "agent_id"):
            for value in [RUN.upper(), None, [], "bad"]:
                r = record()
                r["binding"][key] = value
                self.assertFalse(validate_partial_record(r, expected()))
            e = expected()
            e[key] = OTHER if e[key] == RUN else RUN
            self.assertFalse(validate_partial_record(record(), e))
            del e[key]
            self.assertFalse(validate_partial_record(record(), e))
        r = record()
        r["binding"]["extra"] = RUN
        self.assertFalse(validate_partial_record(r, expected()))

    def test_partition_failures_and_result_only(self):
        for present, missing in [
            ([], expected()["paths"]),
            (["RESULT.txt"], ["partial_result.py", "test_partial_result.py"]),
            (["partial_result.py"] * 2, ["test_partial_result.py", "RESULT.txt"]),
            (["partial_result.py"], ["RESULT.txt"]),
            (["partial_result.py"], ["partial_result.py", "RESULT.txt"]),
            (["extra.py"], expected()["paths"]),
            (["partial_result.py"], ["test_partial_result.py", "RESULT.txt"] * 2),
            ([[]], []),
            (None, []),
            (["partial_result.py"], {}),
        ]:
            r = record()
            r.update(present_paths=present, missing_paths=missing)
            self.assertFalse(validate_partial_record(r, expected()))

    def test_unsafe_paths_even_if_expected(self):
        for path in [
            "/x.py",
            "../x.py",
            "a/../x.py",
            "./x.py",
            "a//x.py",
            "x.py/",
            ".ssh/x.py",
            "a/.git/x.py",
            ".env",
            ".env.local",
            "site-private/x.py",
            "a\\x.py",
            "a*.py",
            "a?.py",
            "a[1].py",
            "a\nx.py",
            "a\x00.py",
            "a\x7f.py",
            "a\x85.py",
            "a\u200b.py",
            "",
            [],
            True,
        ]:
            r, e = record(), expected()
            r.update(present_paths=[path], missing_paths=[])
            e["paths"] = [path]
            with self.subTest(path=path):
                self.assertFalse(validate_partial_record(r, e))
        r, e = record(), expected()
        r.update(present_paths=["src/code.py"], missing_paths=["tests/test_code.py"])
        e["paths"] = ["src/code.py", "tests/test_code.py"]
        self.assertTrue(validate_partial_record(r, e))

    def test_expected_and_limits(self):
        for paths in [
            None,
            [],
            {},
            [[], "partial_result.py"],
            ["partial_result.py"] * 2,
            [f"{i}.py" for i in range(129)],
        ]:
            e = expected()
            e["paths"] = paths
            self.assertFalse(validate_partial_record(record(), e))
        for r, e in [(None, expected()), ([], expected()), (record(), None)]:
            self.assertFalse(validate_partial_record(r, e))
        for count in [1, 128]:
            r, e = record(), expected()
            e["paths"] = [f"{i}.py" for i in range(count)]
            r.update(present_paths=e["paths"][:], missing_paths=[])
            self.assertTrue(validate_partial_record(r, e))


if __name__ == "__main__":
    unittest.main()
