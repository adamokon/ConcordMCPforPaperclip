import unittest
from concord_paperclip.partial_result import classify_partial, validate_partial_record

U1 = "a1b2c3d4-e5f6-4a1b-8c2d-3e4f5a6b7c8d"
U2 = "b2c3d4e5-f6a1-4b2c-9d3e-4f5a6b7c8d9e"
U3 = "c3d4e5f6-a1b2-4c3d-ae4f-5a6b7c8d9e0f"
U4 = "d4e5f6a1-b2c3-4d4e-bf5a-6b7c8d9e0f1a"
HEX64 = "a" * 64


def _facts(**overrides):
    base = {
        "run_id": U1,
        "expected_run_id": U1,
        "worker_status": "error",
        "worker_exit_code": 1,
        "worker_denied_actions": [],
        "native_status": "failed",
        "elapsed_seconds": 484.0,
        "deadline_seconds": 480.0,
        "timeout_observed": True,
        "provider_stopped": True,
        "environment_removed": True,
        "producer_verified": True,
        "allowed_scope": True,
        "auth_error": False,
        "quota_error": False,
        "security_error": False,
        "task_cancelled": False,
        "outer_timeout": False,
        "file_count": 1,
        "cli_status": "SUCCESS",
        "cli_response_empty": True,
    }
    base.update(overrides)
    return base


def _record_and_expected():
    rec = {
        "schema_version": 1,
        "kind": "partial",
        "reason": "final_response_timeout",
        "complete": False,
        "binding": {"task_id": U1, "issue_id": U2, "run_id": U3, "agent_id": U4},
        "snapshot_digest": HEX64,
        "present_paths": ["sol.py"],
        "missing_paths": ["doc.txt"],
    }
    exp = {"task_id": U1, "issue_id": U2, "run_id": U3, "agent_id": U4, "paths": ["sol.py", "doc.txt"]}
    return rec, exp


class TestPartialPeer(unittest.TestCase):
    def test_true_timeout_484_480(self):
        res = classify_partial(_facts(elapsed_seconds=484.0, deadline_seconds=480.0))
        self.assertEqual(res, {"eligible": True, "code": "partial_final_response_timeout"})

    def test_reject_479_9(self):
        res = classify_partial(_facts(elapsed_seconds=479.9, deadline_seconds=480.0))
        self.assertEqual(res, {"eligible": False, "code": "deadline_not_reached"})

    def test_auth_quota_cleanup(self):
        self.assertEqual(classify_partial(_facts(auth_error=True))["code"], "unsafe_auth_error")
        self.assertEqual(classify_partial(_facts(quota_error=True))["code"], "unsafe_quota_error")
        self.assertEqual(
            classify_partial(_facts(environment_removed=False))["code"], "missing_environment_removed"
        )

    def test_mismatched_uuid(self):
        self.assertEqual(classify_partial(_facts(expected_run_id=U2))["code"], "invalid_run_binding")
        rec, exp = _record_and_expected()
        exp["run_id"] = U2
        self.assertFalse(validate_partial_record(rec, exp))

    def test_malformed_partition(self):
        rec, exp = _record_and_expected()
        self.assertTrue(validate_partial_record(rec, exp))
        overlap = dict(rec, present_paths=["sol.py"], missing_paths=["sol.py"])
        self.assertFalse(validate_partial_record(overlap, exp))
        incomplete = dict(rec, present_paths=["sol.py"], missing_paths=[])
        self.assertFalse(validate_partial_record(incomplete, exp))
        no_py = dict(rec, present_paths=["doc.txt"], missing_paths=["sol.py"])
        self.assertFalse(validate_partial_record(no_py, exp))

    def test_cancelled_task_read_only(self):
        res = classify_partial(_facts(task_cancelled=True))
        self.assertEqual(res, {"eligible": True, "code": "partial_final_response_timeout"})
        self.assertEqual(classify_partial(_facts(task_cancelled="invalid"))["code"], "invalid_task_cancelled")


if __name__ == "__main__":
    unittest.main()
