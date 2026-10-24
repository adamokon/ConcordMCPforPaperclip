"""Native diagnostic precedence and shared Process readiness contracts."""

import copy
import unittest

try:
    from readiness import evaluate
except ModuleNotFoundError as exc:
    if exc.name != "readiness":
        raise
    from concord_paperclip.readiness import evaluate


class NativeReadinessTests(unittest.TestCase):
    def probe(self, **changes):
        probe = {
            "observed_at": 1000,
            "agent_status": "idle",
            "adapter_type": "codex_local",
            "enrolled": True,
            "environment_empty": True,
            "active_runs": 0,
            "credential_available": True,
            "provider_auth": "ok",
            "provider_quota": "available",
        }
        probe.update(changes)
        return probe

    def assert_result(self, probe, code, auth=None, quota=None, **timing):
        before = copy.deepcopy(probe)
        result = evaluate(probe, **({"now": 1000} | timing))
        self.assertEqual(probe, before, "evaluate must not mutate its input")
        self.assertEqual(result, {
            "eligible": code == "READY",
            "code": code,
            "auth": probe["provider_auth"] if auth is None else auth,
            "quota": probe["provider_quota"] if quota is None else quota,
        })

    def test_stale_and_future_precede_unavailable_credential(self):
        for observed_at in (939, 1001):
            with self.subTest(observed_at=observed_at):
                self.assert_result(self.probe(
                    observed_at=observed_at, credential_available=False,
                    agent_status="disabled", enrolled=False, active_runs=1,
                    provider_auth="expired", provider_quota="exhausted",
                ), "STALE_PROBE")

    def test_disabled_precedes_enrollment_and_credential(self):
        self.assert_result(self.probe(
            credential_available=False, agent_status="disabled", enrolled=False,
            provider_auth="expired", provider_quota="exhausted",
        ), "AGENT_UNAVAILABLE")

    def test_unenrolled_precedes_credential(self):
        self.assert_result(self.probe(
            credential_available=False, enrolled=False,
            provider_auth="expired", provider_quota="exhausted",
        ), "NOT_ENROLLED")

    def test_missing_credential_still_allows_higher_diagnostics(self):
        for changes, code in (
            ({"observed_at": 939}, "STALE_PROBE"),
            ({"observed_at": 1001}, "STALE_PROBE"),
            ({"agent_status": "disabled"}, "AGENT_UNAVAILABLE"),
            ({"enrolled": False}, "NOT_ENROLLED"),
            ({}, "AUTH_REQUIRED"),
        ):
            with self.subTest(code=code, changes=changes):
                probe = self.probe(**changes)
                del probe["credential_available"]
                self.assert_result(probe, code)

    def test_malformed_ordinary_fields_precede_missing_auth(self):
        invalid_values = {
            "observed_at": (None, True, "1000", float("inf")),
            "agent_status": (None, 1),
            "enrolled": (None, 1),
            "environment_empty": (None, 1),
            "active_runs": (True, -1, 1.5, "0", 10 ** 400),
            "provider_auth": (None, "healthy", [], 1),
            "provider_quota": (None, "healthy", {}, 1),
        }
        for field, values in invalid_values.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assert_result(self.probe(
                        credential_available=False, **{field: value},
                    ), "INVALID_PROBE", auth="unknown", quota="unknown")

    def test_missing_ordinary_fields_are_invalid(self):
        for field in self.probe().keys() - {"credential_available"}:
            with self.subTest(field=field):
                probe = self.probe(credential_available=False)
                del probe[field]
                self.assert_result(probe, "INVALID_PROBE", auth="unknown", quota="unknown")

    def test_credential_requires_identity_true(self):
        for credential in (False, None, 0, 1, 1.0, "true", "yes", [], {}, [True]):
            with self.subTest(credential=credential):
                self.assert_result(self.probe(credential_available=credential), "AUTH_REQUIRED")
        self.assert_result(self.probe(), "READY")

    def test_native_oauth_is_not_required(self):
        self.assert_result(self.probe(), "READY")
        for oauth in (False, None, "not-an-oauth-check"):
            with self.subTest(oauth=oauth):
                self.assert_result(self.probe(oauth_present=oauth), "READY")

    def test_expired_auth_and_unavailable_credential_precede_busy_and_quota(self):
        for credential, auth in ((True, "expired"), (False, "ok"), (False, "unknown")):
            with self.subTest(credential=credential, auth=auth):
                self.assert_result(self.probe(
                    credential_available=credential, provider_auth=auth,
                    active_runs=2, environment_empty=False, provider_quota="exhausted",
                ), "AUTH_REQUIRED")

    def test_valid_metadata_preserved_for_each_native_classification(self):
        cases = (
            ({"observed_at": 939}, "STALE_PROBE"),
            ({"agent_status": "disabled"}, "AGENT_UNAVAILABLE"),
            ({"enrolled": False}, "NOT_ENROLLED"),
            ({}, "AUTH_REQUIRED"),
        )
        for auth in ("unknown", "ok", "expired"):
            for quota in ("unknown", "available", "exhausted"):
                for changes, code in cases:
                    with self.subTest(auth=auth, quota=quota, code=code):
                        self.assert_result(self.probe(
                            credential_available=False, provider_auth=auth,
                            provider_quota=quota, **changes,
                        ), code)

    def test_unknown_metadata_never_inferred_healthy(self):
        self.assert_result(self.probe(provider_auth="unknown", provider_quota="unknown"), "READY")
        self.assert_result(self.probe(
            provider_auth="unknown", provider_quota="unknown", credential_available=False,
        ), "AUTH_REQUIRED")

    def test_native_busy_quota_and_freshness_boundary(self):
        self.assert_result(self.probe(observed_at=940), "READY")
        self.assert_result(self.probe(active_runs=1, provider_quota="exhausted"), "BUSY")
        self.assert_result(self.probe(environment_empty=False), "BUSY")
        self.assert_result(self.probe(provider_quota="exhausted"), "QUOTA_EXHAUSTED")

    def test_invalid_timing_and_age_overflow_are_rejected(self):
        for timing in ({"now": True}, {"now": float("inf")},
                       {"max_age": 0}, {"max_age": True}, {"max_age": "60"}):
            with self.subTest(timing=timing):
                self.assert_result(self.probe(credential_available=False), "INVALID_PROBE",
                                   auth="unknown", quota="unknown", **timing)
        self.assert_result(self.probe(observed_at=-1e308, credential_available=False),
                           "INVALID_PROBE", auth="unknown", quota="unknown", now=1e308)

    def test_process_compatibility_and_precedence(self):
        cases = (
            ({}, "READY"),
            ({"credential_available": False}, "READY"),
            ({"oauth_present": False}, "AUTH_REQUIRED"),
            ({"provider_auth": "expired"}, "AUTH_REQUIRED"),
            ({"oauth_present": False, "active_runs": 1,
              "provider_quota": "exhausted"}, "AUTH_REQUIRED"),
            ({"active_runs": 1, "provider_quota": "exhausted"}, "BUSY"),
            ({"environment_empty": False}, "BUSY"),
            ({"provider_quota": "exhausted"}, "QUOTA_EXHAUSTED"),
            ({"provider_auth": "unknown", "provider_quota": "unknown"}, "READY"),
            ({"observed_at": 939, "agent_status": "disabled",
              "enrolled": False, "oauth_present": False}, "STALE_PROBE"),
            ({"agent_status": "disabled", "enrolled": False,
              "oauth_present": False}, "AGENT_UNAVAILABLE"),
            ({"enrolled": False, "oauth_present": False}, "NOT_ENROLLED"),
            ({"adapter_type": "agy", "enrolled": False}, "UNSUPPORTED_ADAPTER"),
        )
        for changes, code in cases:
            with self.subTest(changes=changes):
                self.assert_result(self.probe(adapter_type="process", oauth_present=True) | changes, code)

    def test_process_oauth_validation_unchanged(self):
        probe = self.probe(adapter_type="process")
        self.assert_result(probe, "INVALID_PROBE", auth="unknown", quota="unknown")
        for oauth in (None, 1, "true"):
            with self.subTest(oauth=oauth):
                self.assert_result(probe | {"oauth_present": oauth}, "INVALID_PROBE",
                                   auth="unknown", quota="unknown")


if __name__ == "__main__":
    unittest.main()
