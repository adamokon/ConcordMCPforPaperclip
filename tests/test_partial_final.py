"""Synthetic, stdlib-only checks; no native runtime or API access."""

import copy
import unittest
from concord_paperclip.partial_result import classify_partial, validate_partial_record

IDS = {
    k: f"00000000-0000-0000-0000-{n:012d}"
    for n, k in enumerate(("task_id", "issue_id", "run_id", "agent_id"), 1)
}


def facts():
    return dict(
        run_id=IDS["run_id"],
        expected_run_id=IDS["run_id"],
        worker_status="error",
        worker_exit_code=1,
        worker_denied_actions=[],
        native_status="failed",
        elapsed_seconds=480,
        deadline_seconds=480,
        timeout_observed=True,
        provider_stopped=True,
        environment_removed=True,
        producer_verified=True,
        allowed_scope=True,
        auth_error=False,
        quota_error=False,
        security_error=False,
        task_cancelled=True,
        outer_timeout=False,
        file_count=1,
        cli_status="SUCCESS",
        cli_response_empty=True,
    )


def receipt():
    expected = dict(IDS, paths=["src/code.py", "notes.txt"])
    record = dict(
        schema_version=1,
        kind="partial",
        reason="final_response_timeout",
        complete=False,
        binding=dict(IDS),
        snapshot_digest="a" * 64,
        present_paths=["src/code.py"],
        missing_paths=["notes.txt"],
    )
    return record, expected


class PartialFinalTests(unittest.TestCase):
    def test_01_deadline_boundary_and_invalid_numbers(self):
        self.assertTrue(classify_partial(facts())["eligible"])
        for field, values in [
            ("elapsed_seconds", [479.999, -1, True, "480", float("nan"), float("inf"), 2**53]),
            ("deadline_seconds", [0, False, "480", float("nan"), float("inf"), 2**53]),
        ]:
            for value in values:
                with self.subTest(field=field, value=value):
                    f = facts()
                    f[field] = value
                    self.assertFalse(classify_partial(f)["eligible"])
        f = facts()
        f["elapsed_seconds"] = 480.001
        self.assertTrue(classify_partial(f)["eligible"])

    def test_02_run_and_worker_binding_fail_closed(self):
        for field, value in [
            ("run_id", IDS["task_id"]),
            ("expected_run_id", "bad"),
            ("worker_exit_code", True),
            ("worker_exit_code", 0),
            ("worker_status", "success"),
            ("worker_denied_actions", ["read"]),
            ("worker_denied_actions", ()),
            ("native_status", "running"),
            ("file_count", True),
            ("file_count", 0),
            ("file_count", 129),
        ]:
            with self.subTest(field=field, value=value):
                f = facts()
                f[field] = value
                self.assertFalse(classify_partial(f)["eligible"])
        self.assertFalse(classify_partial(None)["eligible"])

    def test_03_required_observations_and_response_outcomes(self):
        f = facts()
        for field in list(f):
            with self.subTest(missing=field):
                changed = copy.deepcopy(f)
                del changed[field]
                self.assertFalse(classify_partial(changed)["eligible"])
        for field in (
            "timeout_observed",
            "provider_stopped",
            "environment_removed",
            "producer_verified",
            "allowed_scope",
        ):
            changed = facts()
            changed[field] = 1
            self.assertFalse(classify_partial(changed)["eligible"])
        for field in ("auth_error", "quota_error", "security_error"):
            for value in (True, 0, None):
                changed = facts()
                changed[field] = value
                self.assertFalse(classify_partial(changed)["eligible"])
        for value in (False, None, 0, "", [], {}):
            changed = facts()
            changed["cli_response_empty"] = value
            self.assertFalse(classify_partial(changed)["eligible"])
        changed = facts()
        changed.update(cli_status=None, outer_timeout=True, cli_response_empty=False)
        self.assertTrue(classify_partial(changed)["eligible"])
        changed["outer_timeout"] = False
        self.assertFalse(classify_partial(changed)["eligible"])
        changed = facts()
        changed["cli_status"] = "ERROR"
        self.assertFalse(classify_partial(changed)["eligible"])

    def test_04_all_receipt_bindings_and_digest_shape(self):
        record, expected = receipt()
        self.assertTrue(validate_partial_record(record, expected))
        for key in IDS:
            for value in (
                "bad",
                IDS[key].upper().replace("0", "A", 1),
                "99999999-9999-9999-9999-999999999999",
            ):
                changed = copy.deepcopy(record)
                changed["binding"][key] = value
                self.assertFalse(validate_partial_record(changed, expected))
            changed_expected = copy.deepcopy(expected)
            del changed_expected[key]
            self.assertFalse(validate_partial_record(record, changed_expected))
        for digest in ("a" * 63, "A" * 64, "g" * 64, "a" * 64 + "\n", None, 0):
            changed = copy.deepcopy(record)
            changed["snapshot_digest"] = digest
            self.assertFalse(validate_partial_record(changed, expected))

    def test_05_partial_record_exact_schema_and_no_mutation(self):
        record, expected = receipt()
        before = copy.deepcopy((record, expected))
        self.assertTrue(validate_partial_record(record, expected))
        self.assertEqual((record, expected), before)
        f = facts()
        before_f = copy.deepcopy(f)
        classify_partial(f)
        self.assertEqual(f, before_f)
        for field, value in [
            ("schema_version", True),
            ("schema_version", 2),
            ("kind", "complete"),
            ("reason", "success"),
            ("complete", True),
            ("complete", 0),
            ("binding", dict(IDS, extra="x")),
        ]:
            changed = copy.deepcopy(record)
            changed[field] = value
            self.assertFalse(validate_partial_record(changed, expected))
        for field in record:
            changed = copy.deepcopy(record)
            del changed[field]
            self.assertFalse(validate_partial_record(changed, expected))
        changed = copy.deepcopy(record)
        changed["extra"] = True
        self.assertFalse(validate_partial_record(changed, expected))

    def test_06_paths_partition_and_adversarial_mutations(self):
        for path in (
            "../code.py",
            "/code.py",
            "src//code.py",
            "src/./code.py",
            ".SSH/code.py",
            ".env.local/code.py",
            "site-private/code.py",
            "a\\code.py",
            "x:code.py",
            "x*/code.py",
            "x\x00/code.py",
            "x\u200b/code.py",
        ):
            with self.subTest(path=path):
                record, expected = receipt()
                record["present_paths"] = [path]
                expected["paths"] = [path, "notes.txt"]
                self.assertFalse(validate_partial_record(record, expected))
        for present, missing in [
            ([], ["src/code.py", "notes.txt"]),
            (["src/code.py", "src/code.py"], ["notes.txt"]),
            (["src/code.py"], ["src/code.py", "notes.txt"]),
            (["src/code.py"], []),
            (["notes.txt"], ["src/code.py"]),
        ]:
            record, expected = receipt()
            record.update(present_paths=present, missing_paths=missing)
            self.assertFalse(validate_partial_record(record, expected))
        record, expected = receipt()
        expected["paths"] *= 2
        self.assertFalse(validate_partial_record(record, expected))


if __name__ == "__main__":
    unittest.main()
