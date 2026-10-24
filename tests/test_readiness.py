"""Unit tests for trusted readiness assessment."""

import copy
import unittest

from concord_paperclip.readiness import evaluate


class TestReadiness(unittest.TestCase):
    def setUp(self):
        self.base_probe = {
            "observed_at": 100.0,
            "agent_status": "idle",
            "adapter_type": "process",
            "enrolled": True,
            "environment_empty": True,
            "active_runs": 0,
            "oauth_present": True,
            "provider_auth": "ok",
            "provider_quota": "available",
        }
        self.now = 120.0  # age = 20.0 <= max_age (60.0)

    # 1. Success and uncertainty preservation
    def test_ready_standard(self):
        result = evaluate(self.base_probe, self.now)
        self.assertEqual(
            result,
            {"eligible": True, "code": "READY", "auth": "ok", "quota": "available"},
        )

    def test_ready_with_active_agent_status(self):
        probe = dict(self.base_probe, agent_status="active")
        result = evaluate(probe, self.now)
        self.assertEqual(result["code"], "READY")
        self.assertTrue(result["eligible"])

    def test_ready_preserves_unknown_auth_and_quota(self):
        # Even provider_auth/quota unknown, ready is eligible true, preserving uncertainty
        probe = dict(self.base_probe, provider_auth="unknown", provider_quota="unknown")
        result = evaluate(probe, self.now)
        self.assertEqual(
            result,
            {"eligible": True, "code": "READY", "auth": "unknown", "quota": "unknown"},
        )

    def test_ready_preserves_unknown_auth_only(self):
        probe = dict(self.base_probe, provider_auth="unknown", provider_quota="available")
        result = evaluate(probe, self.now)
        self.assertEqual(
            result,
            {"eligible": True, "code": "READY", "auth": "unknown", "quota": "available"},
        )

    def test_ready_preserves_unknown_quota_only(self):
        probe = dict(self.base_probe, provider_auth="ok", provider_quota="unknown")
        result = evaluate(probe, self.now)
        self.assertEqual(
            result,
            {"eligible": True, "code": "READY", "auth": "ok", "quota": "unknown"},
        )

    def test_extra_probe_keys_ignored(self):
        probe = dict(self.base_probe, extra_metadata={"foo": "bar"}, note="test")
        result = evaluate(probe, self.now)
        self.assertEqual(result["code"], "READY")
        self.assertTrue(result["eligible"])

    def test_default_max_age_and_integer_timestamps(self):
        # probe with int observed_at, integer now, omitting max_age
        probe = dict(self.base_probe, observed_at=100)
        result = evaluate(probe, 120)
        self.assertEqual(result["code"], "READY")
        self.assertTrue(result["eligible"])

        # age = 70 > default max_age 60
        result_stale = evaluate(probe, 170)
        self.assertEqual(result_stale["code"], "STALE_PROBE")
        self.assertFalse(result_stale["eligible"])

    def test_no_mutation(self):
        probe = copy.deepcopy(self.base_probe)
        probe["extra"] = "value"
        original = copy.deepcopy(probe)
        evaluate(probe, self.now, max_age=60)
        self.assertEqual(probe, original)

        # Also verify no mutation on rejection
        probe_rejected = dict(self.base_probe, agent_status="disabled")
        original_rejected = copy.deepcopy(probe_rejected)
        evaluate(probe_rejected, self.now)
        self.assertEqual(probe_rejected, original_rejected)

    # 2. Staleness, boundary conditions, future rejection
    def test_exact_expiry_accepted_at_max_age(self):
        # age = now - observed_at = 160.0 - 100.0 = 60.0 == max_age
        now = 160.0
        result = evaluate(self.base_probe, now=now, max_age=60.0)
        self.assertEqual(result["code"], "READY")
        self.assertTrue(result["eligible"])

    def test_age_just_under_max_age_accepted(self):
        now = 159.999
        result = evaluate(self.base_probe, now=now, max_age=60.0)
        self.assertEqual(result["code"], "READY")
        self.assertTrue(result["eligible"])

    def test_older_than_max_age_rejected(self):
        now = 160.001
        result = evaluate(self.base_probe, now=now, max_age=60.0)
        self.assertEqual(
            result,
            {"eligible": False, "code": "STALE_PROBE", "auth": "ok", "quota": "available"},
        )

    def test_observed_at_now_accepted(self):
        # age = 0
        result = evaluate(self.base_probe, now=100.0, max_age=60.0)
        self.assertEqual(result["code"], "READY")
        self.assertTrue(result["eligible"])

    def test_future_probe_rejected(self):
        # observed_at > now
        now = 99.999
        result = evaluate(self.base_probe, now=now, max_age=60.0)
        self.assertEqual(
            result,
            {"eligible": False, "code": "STALE_PROBE", "auth": "ok", "quota": "available"},
        )

    def test_custom_max_age(self):
        result = evaluate(self.base_probe, now=110.0, max_age=5.0)  # age 10 > 5
        self.assertEqual(result["code"], "STALE_PROBE")
        self.assertFalse(result["eligible"])

        result_ok = evaluate(self.base_probe, now=110.0, max_age=15.0)  # age 10 <= 15
        self.assertEqual(result_ok["code"], "READY")
        self.assertTrue(result_ok["eligible"])

    # 3. Individual rejection rules and preserving valid auth/quota
    def test_agent_unavailable_disabled_states(self):
        for status in ["disabled", "offline", "paused", "error", "maintenance", ""]:
            probe = dict(
                self.base_probe,
                agent_status=status,
                provider_auth="unknown",
                provider_quota="available",
            )
            result = evaluate(probe, self.now)
            self.assertEqual(
                result,
                {
                    "eligible": False,
                    "code": "AGENT_UNAVAILABLE",
                    "auth": "unknown",
                    "quota": "available",
                },
            )

    def test_unsupported_adapter(self):
        for adapter in ["docker", "k8s", "Process", "thread"]:
            probe = dict(
                self.base_probe,
                adapter_type=adapter,
                provider_auth="ok",
                provider_quota="unknown",
            )
            result = evaluate(probe, self.now)
            self.assertEqual(
                result,
                {
                    "eligible": False,
                    "code": "UNSUPPORTED_ADAPTER",
                    "auth": "ok",
                    "quota": "unknown",
                },
            )

    def test_not_enrolled(self):
        probe = dict(
            self.base_probe,
            enrolled=False,
            provider_auth="expired",
            provider_quota="exhausted",
        )
        result = evaluate(probe, self.now)
        self.assertEqual(
            result,
            {
                "eligible": False,
                "code": "NOT_ENROLLED",
                "auth": "expired",
                "quota": "exhausted",
            },
        )

    def test_auth_required_oauth_present_false(self):
        probe = dict(
            self.base_probe,
            oauth_present=False,
            provider_auth="ok",
            provider_quota="available",
        )
        result = evaluate(probe, self.now)
        self.assertEqual(
            result,
            {
                "eligible": False,
                "code": "AUTH_REQUIRED",
                "auth": "ok",
                "quota": "available",
            },
        )

    def test_auth_required_provider_auth_expired(self):
        probe = dict(
            self.base_probe,
            oauth_present=True,
            provider_auth="expired",
            provider_quota="available",
        )
        result = evaluate(probe, self.now)
        self.assertEqual(
            result,
            {
                "eligible": False,
                "code": "AUTH_REQUIRED",
                "auth": "expired",
                "quota": "available",
            },
        )

    def test_auth_required_both_false_and_expired(self):
        probe = dict(
            self.base_probe,
            oauth_present=False,
            provider_auth="expired",
            provider_quota="available",
        )
        result = evaluate(probe, self.now)
        self.assertEqual(
            result,
            {
                "eligible": False,
                "code": "AUTH_REQUIRED",
                "auth": "expired",
                "quota": "available",
            },
        )

    def test_busy_active_runs_greater_than_zero(self):
        probe = dict(
            self.base_probe,
            active_runs=1,
            provider_auth="ok",
            provider_quota="available",
        )
        result = evaluate(probe, self.now)
        self.assertEqual(
            result,
            {"eligible": False, "code": "BUSY", "auth": "ok", "quota": "available"},
        )

    def test_busy_environment_not_empty(self):
        probe = dict(
            self.base_probe,
            environment_empty=False,
            provider_auth="ok",
            provider_quota="available",
        )
        result = evaluate(probe, self.now)
        self.assertEqual(
            result,
            {"eligible": False, "code": "BUSY", "auth": "ok", "quota": "available"},
        )

    def test_busy_both_runs_and_not_empty(self):
        probe = dict(
            self.base_probe,
            active_runs=3,
            environment_empty=False,
            provider_auth="ok",
            provider_quota="available",
        )
        result = evaluate(probe, self.now)
        self.assertEqual(
            result,
            {"eligible": False, "code": "BUSY", "auth": "ok", "quota": "available"},
        )

    def test_quota_exhausted(self):
        probe = dict(
            self.base_probe,
            provider_quota="exhausted",
            provider_auth="ok",
        )
        result = evaluate(probe, self.now)
        self.assertEqual(
            result,
            {"eligible": False, "code": "QUOTA_EXHAUSTED", "auth": "ok", "quota": "exhausted"},
        )

    # 4. Precedence tests
    def test_precedence_stale_over_disabled_agent(self):
        probe = dict(self.base_probe, observed_at=50.0, agent_status="disabled")
        result = evaluate(probe, now=120.0, max_age=60.0)  # age 70 > 60
        self.assertEqual(result["code"], "STALE_PROBE")

    def test_precedence_future_over_disabled_agent(self):
        probe = dict(self.base_probe, observed_at=150.0, agent_status="disabled")
        result = evaluate(probe, now=120.0, max_age=60.0)
        self.assertEqual(result["code"], "STALE_PROBE")

    def test_precedence_agent_unavailable_over_unsupported_adapter(self):
        probe = dict(self.base_probe, agent_status="disabled", adapter_type="docker")
        result = evaluate(probe, self.now)
        self.assertEqual(result["code"], "AGENT_UNAVAILABLE")

    def test_precedence_unsupported_adapter_over_not_enrolled(self):
        probe = dict(self.base_probe, adapter_type="docker", enrolled=False)
        result = evaluate(probe, self.now)
        self.assertEqual(result["code"], "UNSUPPORTED_ADAPTER")

    def test_precedence_not_enrolled_over_auth_required(self):
        probe = dict(self.base_probe, enrolled=False, oauth_present=False)
        result = evaluate(probe, self.now)
        self.assertEqual(result["code"], "NOT_ENROLLED")

        probe_expired = dict(self.base_probe, enrolled=False, provider_auth="expired")
        result_expired = evaluate(probe_expired, self.now)
        self.assertEqual(result_expired["code"], "NOT_ENROLLED")

    def test_precedence_auth_required_over_busy(self):
        probe = dict(self.base_probe, oauth_present=False, active_runs=2, environment_empty=False)
        result = evaluate(probe, self.now)
        self.assertEqual(result["code"], "AUTH_REQUIRED")

        probe_expired = dict(self.base_probe, provider_auth="expired", active_runs=2)
        result_expired = evaluate(probe_expired, self.now)
        self.assertEqual(result_expired["code"], "AUTH_REQUIRED")

    def test_precedence_busy_over_quota_exhausted(self):
        probe = dict(self.base_probe, active_runs=1, provider_quota="exhausted")
        result = evaluate(probe, self.now)
        self.assertEqual(result["code"], "BUSY")

        probe_env = dict(self.base_probe, environment_empty=False, provider_quota="exhausted")
        result_env = evaluate(probe_env, self.now)
        self.assertEqual(result_env["code"], "BUSY")

    # 5. Malformed input and INVALID_PROBE handling
    def assert_invalid(self, result):
        self.assertEqual(
            result,
            {"eligible": False, "code": "INVALID_PROBE", "auth": "unknown", "quota": "unknown"},
        )

    def test_probe_not_dict(self):
        for bad_probe in [None, [], 123, "string", True, False, object()]:
            self.assert_invalid(evaluate(bad_probe, self.now))

    def test_now_invalid_type_or_value(self):
        for bad_now in [None, "120", True, False, [120], float("nan"), float("inf"), -float("inf"), 10**1000]:
            self.assert_invalid(evaluate(self.base_probe, bad_now))

    def test_max_age_invalid_type_or_value(self):
        for bad_max_age in [None, "60", True, False, [60], float("nan"), float("inf"), -float("inf"), 0, 0.0, -1, -60.0]:
            self.assert_invalid(evaluate(self.base_probe, self.now, bad_max_age))

    def test_missing_required_keys(self):
        for key in [
            "observed_at",
            "agent_status",
            "adapter_type",
            "enrolled",
            "environment_empty",
            "active_runs",
            "oauth_present",
            "provider_auth",
            "provider_quota",
        ]:
            probe = dict(self.base_probe)
            del probe[key]
            self.assert_invalid(evaluate(probe, self.now))

    def test_observed_at_invalid(self):
        for bad_val in [None, "100", True, False, [100], float("nan"), float("inf"), -float("inf"), 10**1000]:
            probe = dict(self.base_probe, observed_at=bad_val)
            self.assert_invalid(evaluate(probe, self.now))

    def test_agent_status_invalid(self):
        for bad_val in [None, 123, True, False, ["idle"], {}]:
            probe = dict(self.base_probe, agent_status=bad_val)
            self.assert_invalid(evaluate(probe, self.now))

    def test_adapter_type_invalid(self):
        for bad_val in [None, 123, True, False, ["process"], {}]:
            probe = dict(self.base_probe, adapter_type=bad_val)
            self.assert_invalid(evaluate(probe, self.now))

    def test_enrolled_invalid(self):
        for bad_val in [None, 1, 0, "True", "False", [True]]:
            probe = dict(self.base_probe, enrolled=bad_val)
            self.assert_invalid(evaluate(probe, self.now))

    def test_environment_empty_invalid(self):
        for bad_val in [None, 1, 0, "True", "False", [False]]:
            probe = dict(self.base_probe, environment_empty=bad_val)
            self.assert_invalid(evaluate(probe, self.now))

    def test_active_runs_invalid(self):
        # Must be nonnegative int not bool
        for bad_val in [None, -1, -100, 0.0, 1.5, True, False, "0", [0], 10**1000]:
            probe = dict(self.base_probe, active_runs=bad_val)
            self.assert_invalid(evaluate(probe, self.now))

    def test_oauth_present_invalid(self):
        for bad_val in [None, 1, 0, "True", "False", [True]]:
            probe = dict(self.base_probe, oauth_present=bad_val)
            self.assert_invalid(evaluate(probe, self.now))

    def test_provider_auth_invalid_enums(self):
        for bad_val in [None, "authenticated", "valid", "none", "OK", "EXPIRED", 123]:
            probe = dict(self.base_probe, provider_auth=bad_val)
            self.assert_invalid(evaluate(probe, self.now))

    def test_provider_quota_invalid_enums(self):
        for bad_val in [None, "full", "unlimited", "none", "AVAILABLE", "EXHAUSTED", 123]:
            probe = dict(self.base_probe, provider_quota=bad_val)
            self.assert_invalid(evaluate(probe, self.now))

    def test_numeric_subtraction_overflow(self):
        # Test overflow in now - observed_at
        probe = dict(self.base_probe, observed_at=-1e308)
        self.assert_invalid(evaluate(probe, now=1e308))


if __name__ == "__main__":
    unittest.main()
