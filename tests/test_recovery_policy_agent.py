"""
test_recovery_policy.py - Comprehensive test suite for recovery_policy.py.

Tests cover all required behaviors specified in TASK.txt:
1. Policy off / scopes (disabled policy, repo/agent allowlists, company/project isolation)
2. Canonical binding and UUID validation (lowercase hex 8-4-4-4-12, reject noncanonical/malformed)
3. Truthy forged flags (reject bools masquerading as numeric/ints, int/str masquerading as bools)
4. Finite clocks (reject nan, +inf, -inf, string timestamps)
5. Future / stale observations (evidence in future, evidence older than max_evidence_age)
6. Busy slots (other_run_active, cleanup_incomplete, queued/running/unknown statuses)
7. Exact native success (native_status == "succeeded" + cleanup_complete -> receive)
8. Allowed pre-provider failure retry (proven no provider start, no effects, trusted attestation, within budget)
9. Quota / auth / security / no cleanup / unknown effects refusal
10. Budget exhaustion (retries_used >= max_retries refuses retry)
11. Safe successor adoption after budget reservation (action bind for matching new_run even if budget exhausted)
12. Strict error mode and RecoveryPolicyError export
"""

import unittest

from concord_paperclip.recovery_policy import (
    RecoveryPolicyError,
    decide_recovery,
    is_canonical_uuid,
)

VALID_TASK_ID = "00000000-0000-4000-8000-000000000001"
VALID_ISSUE_ID = "11111111-2222-3333-4444-555555555555"
VALID_AGENT_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
VALID_SOURCE_RUN_ID = "22222222-3333-4444-5555-666666666666"
VALID_ATTEMPT_ID = "33333333-4444-5555-6666-777777777777"
VALID_COMPANY_ID = "44444444-5555-6666-7777-888888888888"
VALID_PROJECT_ID = "55555555-6666-7777-8888-999999999999"
VALID_ACTION_ID = "66666666-7777-8888-9999-000000000000"
VALID_NEW_RUN_ID = "77777777-8888-9999-aaaa-bbbbbbbbbbbb"


def make_policy(**overrides):
    base = {
        "enabled": True,
        "policy_id": "root-policy-01",
        "allowed_repos": ["repo-a", "repo-b"],
        "allowed_agents": [VALID_AGENT_ID],
        "company_id": VALID_COMPANY_ID,
        "project_id": VALID_PROJECT_ID,
        "max_retries": 2,
        "max_evidence_age": 30.0,
    }
    base.update(overrides)
    return base


def make_expected(**overrides):
    base = {
        "task_id": VALID_TASK_ID,
        "issue_id": VALID_ISSUE_ID,
        "agent_id": VALID_AGENT_ID,
        "source_run_id": VALID_SOURCE_RUN_ID,
        "attempt_id": VALID_ATTEMPT_ID,
        "company_id": VALID_COMPANY_ID,
        "project_id": VALID_PROJECT_ID,
        "repo": "repo-a",
        "retries_used": 0,
    }
    base.update(overrides)
    return base


def make_evidence(**overrides):
    base = {
        "task_id": VALID_TASK_ID,
        "issue_id": VALID_ISSUE_ID,
        "agent_id": VALID_AGENT_ID,
        "source_run_id": VALID_SOURCE_RUN_ID,
        "attempt_id": VALID_ATTEMPT_ID,
        "company_id": VALID_COMPANY_ID,
        "project_id": VALID_PROJECT_ID,
        "observed_at": 1000.0,
        "native_status": "succeeded",
        "cleanup_complete": True,
        "other_run_active": False,
        "provider_started": True,
        "effects": "completed",
        "attestation": "trusted_worker_result_v1",
        "recovery_action_id": None,
        "error_kind": None,
        "paused": False,
        "terminated": False,
        "new_run": None,
    }
    base.update(overrides)
    return base


class TestPolicyScope(unittest.TestCase):
    """Test policy enable status and scope boundaries."""

    def test_policy_disabled_blocks(self):
        policy = make_policy(enabled=False)
        expected = make_expected()
        evidence = make_evidence()
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "policy_disabled")

    def test_repo_not_allowed_blocks(self):
        policy = make_policy(allowed_repos=["repo-other"])
        expected = make_expected(repo="repo-a")
        evidence = make_evidence()
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "repo_not_allowed")

    def test_agent_not_allowed_blocks(self):
        other_agent = "99999999-9999-9999-9999-999999999999"
        policy = make_policy(allowed_agents=[other_agent])
        expected = make_expected(agent_id=VALID_AGENT_ID)
        evidence = make_evidence(agent_id=VALID_AGENT_ID)
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "agent_not_allowed")

    def test_company_mismatch_blocks(self):
        other_co = "99999999-9999-9999-9999-999999999999"
        policy = make_policy(company_id=other_co)
        expected = make_expected()
        evidence = make_evidence()
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "scope_company_project_mismatch")

    def test_project_mismatch_blocks(self):
        other_proj = "99999999-9999-9999-9999-999999999999"
        policy = make_policy(project_id=other_proj)
        expected = make_expected()
        evidence = make_evidence()
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "scope_company_project_mismatch")


class TestCanonicalBindingAndUUIDs(unittest.TestCase):
    """Test strict canonical UUID parsing and identity mismatch refusals."""

    def test_canonical_uuid_helper(self):
        # Valid canonical lowercase UUID
        self.assertTrue(is_canonical_uuid("08c7df02-3dba-4bc1-84e3-f361e4d543d4"))
        # Uppercase hex must fail
        self.assertFalse(is_canonical_uuid("08C7DF02-3DBA-4BC1-84E3-F361E4D543D4"))
        # Non-hex characters
        self.assertFalse(is_canonical_uuid("08c7df02-3dba-4bc1-84e3-f361e4d543dg"))
        # Missing hyphens
        self.assertFalse(is_canonical_uuid("08c7df023dba4bc184e3f361e4d543d4"))
        # Wrong length
        self.assertFalse(is_canonical_uuid("08c7df02-3dba-4bc1-84e3-f361e4d543d"))
        # Non-string
        self.assertFalse(is_canonical_uuid(123456789))
        self.assertFalse(is_canonical_uuid(None))

    def test_noncanonical_uuid_in_expected_blocks(self):
        expected = make_expected(task_id="08C7DF02-3DBA-4BC1-84E3-F361E4D543D4")
        policy = make_policy()
        evidence = make_evidence()
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "malformed_expected")

    def test_noncanonical_uuid_in_evidence_blocks(self):
        evidence = make_evidence(task_id="08C7DF02-3DBA-4BC1-84E3-F361E4D543D4")
        policy = make_policy()
        expected = make_expected()
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "malformed_evidence")

    def test_all_identity_field_mismatches_refused(self):
        mismatched_id = "99999999-9999-9999-9999-999999999999"
        fields = [
            "task_id",
            "issue_id",
            "agent_id",
            "source_run_id",
            "attempt_id",
            "company_id",
            "project_id",
        ]
        for f in fields:
            policy = make_policy()
            expected = make_expected()
            evidence = make_evidence(**{f: mismatched_id})
            res = decide_recovery(policy, expected, evidence, 1005.0)
            self.assertEqual(res["action"], "block", f"Failed for field mismatch: {f}")
            self.assertEqual(res["code"], "identity_mismatch", f"Failed code for field: {f}")


class TestTruthyForgedFlags(unittest.TestCase):
    """Test rejection of boolean masquerading as int/numeric and non-bool flags."""

    def test_retries_used_bool_rejected(self):
        # bool is a subclass of int in Python, must be explicitly rejected
        policy = make_policy()
        expected = make_expected(retries_used=True)
        evidence = make_evidence()
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "malformed_expected")

    def test_max_retries_bool_rejected(self):
        policy = make_policy(max_retries=True)
        expected = make_expected()
        evidence = make_evidence()
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "malformed_policy")

    def test_cleanup_complete_int_rejected(self):
        policy = make_policy()
        expected = make_expected()
        evidence = make_evidence(cleanup_complete=1)
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "malformed_evidence")

    def test_other_run_active_string_rejected(self):
        policy = make_policy()
        expected = make_expected()
        evidence = make_evidence(other_run_active="false")
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "malformed_evidence")

    def test_provider_started_int_rejected(self):
        policy = make_policy()
        expected = make_expected()
        evidence = make_evidence(provider_started=0)
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "malformed_evidence")

    def test_now_as_bool_rejected(self):
        policy = make_policy()
        expected = make_expected()
        evidence = make_evidence()
        res = decide_recovery(policy, expected, evidence, True)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "nonfinite_clock")

    def test_observed_at_as_bool_rejected(self):
        policy = make_policy()
        expected = make_expected()
        evidence = make_evidence(observed_at=False)
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "nonfinite_clock")


class TestFiniteClocks(unittest.TestCase):
    """Test non-finite clocks (nan, +inf, -inf) rejection."""

    def test_now_nan_rejected(self):
        policy = make_policy()
        expected = make_expected()
        evidence = make_evidence()
        res = decide_recovery(policy, expected, evidence, float("nan"))
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "nonfinite_clock")

    def test_now_inf_rejected(self):
        policy = make_policy()
        expected = make_expected()
        evidence = make_evidence()
        res = decide_recovery(policy, expected, evidence, float("inf"))
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "nonfinite_clock")

    def test_observed_at_nan_rejected(self):
        policy = make_policy()
        expected = make_expected()
        evidence = make_evidence(observed_at=float("nan"))
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "nonfinite_clock")

    def test_observed_at_neginf_rejected(self):
        policy = make_policy()
        expected = make_expected()
        evidence = make_evidence(observed_at=float("-inf"))
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "nonfinite_clock")


class TestObservationsTimeWindow(unittest.TestCase):
    """Test future and stale evidence rejection."""

    def test_future_observation_blocked(self):
        policy = make_policy(max_evidence_age=30.0)
        expected = make_expected()
        # Evidence timestamp is in the future relative to `now`
        evidence = make_evidence(observed_at=1050.0)
        res = decide_recovery(policy, expected, evidence, 1000.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "future_evidence")

    def test_stale_observation_blocked(self):
        policy = make_policy(max_evidence_age=30.0)
        expected = make_expected()
        # Age is 35 seconds, policy allows max 30.0
        evidence = make_evidence(observed_at=965.0)
        res = decide_recovery(policy, expected, evidence, 1000.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "stale_evidence")

    def test_fresh_observation_allowed(self):
        policy = make_policy(max_evidence_age=30.0)
        expected = make_expected()
        # Age is 10 seconds, within the 30s window
        evidence = make_evidence(observed_at=990.0)
        res = decide_recovery(policy, expected, evidence, 1000.0)
        self.assertEqual(res["action"], "receive")
        self.assertEqual(res["code"], "native_succeeded")


class TestBusySlotsAndCleanup(unittest.TestCase):
    """Test wait actions on unproven cleanup or in-progress states."""

    def test_other_run_active_waits(self):
        policy = make_policy()
        expected = make_expected()
        evidence = make_evidence(other_run_active=True)
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "wait")
        self.assertEqual(res["code"], "other_run_active")

    def test_cleanup_incomplete_waits(self):
        policy = make_policy()
        expected = make_expected()
        evidence = make_evidence(cleanup_complete=False)
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "wait")
        self.assertEqual(res["code"], "cleanup_incomplete")

    def test_in_progress_statuses_wait(self):
        policy = make_policy()
        expected = make_expected()
        for st in ("queued", "running", "unknown"):
            evidence = make_evidence(native_status=st)
            res = decide_recovery(policy, expected, evidence, 1005.0)
            self.assertEqual(res["action"], "wait")
            self.assertEqual(res["code"], f"status_{st}")

    def test_native_succeeded_without_cleanup_waits(self):
        policy = make_policy()
        expected = make_expected()
        evidence = make_evidence(native_status="succeeded", cleanup_complete=False)
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "wait")
        self.assertEqual(res["code"], "cleanup_incomplete")


class TestExactNativeSuccess(unittest.TestCase):
    """Test receive decision on proven exact native success."""

    def test_receive_on_succeeded_and_cleaned(self):
        policy = make_policy()
        expected = make_expected()
        evidence = make_evidence(
            native_status="succeeded",
            cleanup_complete=True,
            other_run_active=False,
            effects="completed",
        )
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "receive")
        self.assertEqual(res["code"], "native_succeeded")


class TestAllowedPreProviderFailureRetry(unittest.TestCase):
    """Test allowed retry on proven pre-provider transient failures."""

    def test_pre_provider_transient_allowed_retry(self):
        policy = make_policy(max_retries=2)
        expected = make_expected(retries_used=0)
        evidence = make_evidence(
            native_status="failed",
            cleanup_complete=True,
            other_run_active=False,
            provider_started=False,
            effects="not_performed",
            attestation="trusted_pre_provider_v1",
            error_kind="pre_provider_transient",
            recovery_action_id=VALID_ACTION_ID,
        )
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "retry")
        self.assertEqual(res["code"], "retry_pre_provider_transient")

    def test_timed_out_with_explicit_pre_provider_attestation_retry(self):
        policy = make_policy(max_retries=2)
        expected = make_expected(retries_used=1)
        evidence = make_evidence(
            native_status="timed_out",
            cleanup_complete=True,
            other_run_active=False,
            provider_started=False,
            effects="not_performed",
            attestation="trusted_pre_provider_v1",
            error_kind="pre_provider_transient",
            recovery_action_id=VALID_ACTION_ID,
        )
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "retry")
        self.assertEqual(res["code"], "retry_pre_provider_transient")


class TestRefusalsAndUnknownEffects(unittest.TestCase):
    """Test refusal of auth, quota, security, unknown effects, and cancelled."""

    def test_refusal_auth(self):
        policy = make_policy()
        expected = make_expected()
        evidence = make_evidence(error_kind="auth")
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "auth_error")

    def test_refusal_quota(self):
        policy = make_policy()
        expected = make_expected()
        evidence = make_evidence(error_kind="quota")
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "quota_error")

    def test_refusal_security(self):
        policy = make_policy()
        expected = make_expected()
        evidence = make_evidence(error_kind="security")
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "security_error")

    def test_refusal_paused(self):
        policy = make_policy()
        expected = make_expected()
        evidence = make_evidence(paused=True)
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "paused")

    def test_refusal_terminated(self):
        policy = make_policy()
        expected = make_expected()
        evidence = make_evidence(terminated=True)
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "terminated")

    def test_refusal_provider_failure(self):
        policy = make_policy()
        expected = make_expected()
        evidence = make_evidence(
            native_status="failed",
            cleanup_complete=True,
            other_run_active=False,
            provider_started=False,
            effects="not_performed",
            attestation="trusted_pre_provider_v1",
            error_kind="provider_failure",
            recovery_action_id=VALID_ACTION_ID,
        )
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "provider_failure")

    def test_refusal_provider_started_true(self):
        policy = make_policy()
        expected = make_expected()
        evidence = make_evidence(
            native_status="failed",
            cleanup_complete=True,
            other_run_active=False,
            provider_started=True,
            effects="not_performed",
            attestation="trusted_pre_provider_v1",
            error_kind="pre_provider_transient",
            recovery_action_id=VALID_ACTION_ID,
        )
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "unknown_effects")

    def test_refusal_provider_started_none(self):
        policy = make_policy()
        expected = make_expected()
        evidence = make_evidence(
            native_status="failed",
            cleanup_complete=True,
            other_run_active=False,
            provider_started=None,
            effects="not_performed",
            attestation="trusted_pre_provider_v1",
            error_kind="pre_provider_transient",
            recovery_action_id=VALID_ACTION_ID,
        )
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "unknown_effects")

    def test_refusal_effects_completed_on_failure(self):
        policy = make_policy()
        expected = make_expected()
        evidence = make_evidence(
            native_status="failed",
            cleanup_complete=True,
            other_run_active=False,
            provider_started=False,
            effects="completed",
            attestation="trusted_pre_provider_v1",
            error_kind="pre_provider_transient",
            recovery_action_id=VALID_ACTION_ID,
        )
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "unknown_effects")

    def test_refusal_effects_unknown(self):
        policy = make_policy()
        expected = make_expected()
        evidence = make_evidence(
            native_status="failed",
            cleanup_complete=True,
            other_run_active=False,
            provider_started=False,
            effects="unknown",
            attestation="trusted_pre_provider_v1",
            error_kind="pre_provider_transient",
            recovery_action_id=VALID_ACTION_ID,
        )
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "unknown_effects")

    def test_refusal_cancelled_not_reclassified_as_success(self):
        policy = make_policy()
        expected = make_expected()
        evidence = make_evidence(
            native_status="cancelled",
            cleanup_complete=True,
            other_run_active=False,
        )
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "cancelled")

    def test_timeout_alone_is_not_no_effects_proof(self):
        policy = make_policy()
        expected = make_expected()
        # timed_out without provider_started=False or with effects=unknown
        evidence = make_evidence(
            native_status="timed_out",
            cleanup_complete=True,
            other_run_active=False,
            provider_started=None,
            effects="unknown",
            attestation=None,
            error_kind="unknown",
        )
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "unknown_effects")

    def test_untrusted_attestation_refused(self):
        policy = make_policy()
        expected = make_expected()
        evidence = make_evidence(
            native_status="failed",
            cleanup_complete=True,
            other_run_active=False,
            provider_started=False,
            effects="not_performed",
            attestation="trusted_worker_result_v1",  # not pre_provider_v1
            error_kind="pre_provider_transient",
            recovery_action_id=VALID_ACTION_ID,
        )
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "untrusted_attestation")

    def test_missing_recovery_action_refused(self):
        policy = make_policy()
        expected = make_expected()
        evidence = make_evidence(
            native_status="failed",
            cleanup_complete=True,
            other_run_active=False,
            provider_started=False,
            effects="not_performed",
            attestation="trusted_pre_provider_v1",
            error_kind="pre_provider_transient",
            recovery_action_id=None,
        )
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "missing_recovery_action")


class TestBudgetExhaustion(unittest.TestCase):
    """Test retry refusal once retries_used reaches max_retries."""

    def test_retries_used_equals_max_retries_blocked(self):
        policy = make_policy(max_retries=2)
        expected = make_expected(retries_used=2)
        evidence = make_evidence(
            native_status="failed",
            cleanup_complete=True,
            other_run_active=False,
            provider_started=False,
            effects="not_performed",
            attestation="trusted_pre_provider_v1",
            error_kind="pre_provider_transient",
            recovery_action_id=VALID_ACTION_ID,
        )
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "retry_budget_exhausted")

    def test_retries_used_exceeds_max_retries_blocked(self):
        policy = make_policy(max_retries=1)
        expected = make_expected(retries_used=3)
        evidence = make_evidence(
            native_status="failed",
            cleanup_complete=True,
            other_run_active=False,
            provider_started=False,
            effects="not_performed",
            attestation="trusted_pre_provider_v1",
            error_kind="pre_provider_transient",
            recovery_action_id=VALID_ACTION_ID,
        )
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "retry_budget_exhausted")


class TestSafeSuccessorAdoption(unittest.TestCase):
    """Test evidence.new_run adoption even after retry budget was consumed."""

    def test_safe_successor_adopted_after_budget_consumed(self):
        policy = make_policy(max_retries=2)
        # Budget exhausted!
        expected = make_expected(retries_used=2)
        new_run_dict = {
            "id": VALID_NEW_RUN_ID,
            "status": "queued",
            "task_id": VALID_TASK_ID,
            "issue_id": VALID_ISSUE_ID,
            "agent_id": VALID_AGENT_ID,
            "company_id": VALID_COMPANY_ID,
            "project_id": VALID_PROJECT_ID,
            "source_run_id": VALID_SOURCE_RUN_ID,
            "recovery_action_id": VALID_ACTION_ID,
        }
        evidence = make_evidence(
            recovery_action_id=VALID_ACTION_ID,
            new_run=new_run_dict,
        )
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "bind")
        self.assertEqual(res["code"], "bind_successor")

    def test_safe_successor_running_and_succeeded_allowed(self):
        policy = make_policy(max_retries=2)
        expected = make_expected(retries_used=2)
        for st in ("running", "succeeded"):
            new_run_dict = {
                "id": VALID_NEW_RUN_ID,
                "status": st,
                "task_id": VALID_TASK_ID,
                "issue_id": VALID_ISSUE_ID,
                "agent_id": VALID_AGENT_ID,
                "company_id": VALID_COMPANY_ID,
                "project_id": VALID_PROJECT_ID,
                "source_run_id": VALID_SOURCE_RUN_ID,
                "recovery_action_id": VALID_ACTION_ID,
            }
            evidence = make_evidence(
                recovery_action_id=VALID_ACTION_ID,
                new_run=new_run_dict,
            )
            res = decide_recovery(policy, expected, evidence, 1005.0)
            self.assertEqual(res["action"], "bind")
            self.assertEqual(res["code"], "bind_successor")

    def test_successor_scope_mismatch_blocks(self):
        policy = make_policy()
        expected = make_expected()
        other_agent = "99999999-9999-9999-9999-999999999999"
        new_run_dict = {
            "id": VALID_NEW_RUN_ID,
            "status": "queued",
            "task_id": VALID_TASK_ID,
            "issue_id": VALID_ISSUE_ID,
            "agent_id": other_agent,  # mismatch
            "company_id": VALID_COMPANY_ID,
            "project_id": VALID_PROJECT_ID,
            "source_run_id": VALID_SOURCE_RUN_ID,
            "recovery_action_id": VALID_ACTION_ID,
        }
        evidence = make_evidence(
            recovery_action_id=VALID_ACTION_ID,
            new_run=new_run_dict,
        )
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "successor_mismatch")

    def test_successor_recovery_action_mismatch_blocks(self):
        policy = make_policy()
        expected = make_expected()
        other_action = "99999999-9999-9999-9999-999999999999"
        new_run_dict = {
            "id": VALID_NEW_RUN_ID,
            "status": "queued",
            "task_id": VALID_TASK_ID,
            "issue_id": VALID_ISSUE_ID,
            "agent_id": VALID_AGENT_ID,
            "company_id": VALID_COMPANY_ID,
            "project_id": VALID_PROJECT_ID,
            "source_run_id": VALID_SOURCE_RUN_ID,
            "recovery_action_id": other_action,  # does not match evidence
        }
        evidence = make_evidence(
            recovery_action_id=VALID_ACTION_ID,
            new_run=new_run_dict,
        )
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "successor_mismatch")

    def test_successor_invalid_status_blocks(self):
        policy = make_policy()
        expected = make_expected()
        for bad_status in ("failed", "cancelled", "timed_out", "unknown"):
            new_run_dict = {
                "id": VALID_NEW_RUN_ID,
                "status": bad_status,
                "task_id": VALID_TASK_ID,
                "issue_id": VALID_ISSUE_ID,
                "agent_id": VALID_AGENT_ID,
                "company_id": VALID_COMPANY_ID,
                "project_id": VALID_PROJECT_ID,
                "source_run_id": VALID_SOURCE_RUN_ID,
                "recovery_action_id": VALID_ACTION_ID,
            }
            evidence = make_evidence(
                recovery_action_id=VALID_ACTION_ID,
                new_run=new_run_dict,
            )
            res = decide_recovery(policy, expected, evidence, 1005.0)
            self.assertEqual(res["action"], "block")
            self.assertEqual(res["code"], "successor_mismatch")


class TestStrictModeAndErrors(unittest.TestCase):
    """Test RecoveryPolicyError export and strict raise_on_error behavior."""

    def test_recovery_policy_error_structure(self):
        err = RecoveryPolicyError("custom_code", "Detailed error message")
        self.assertIsInstance(err, ValueError)
        self.assertEqual(err.code, "custom_code")
        self.assertIn("custom_code", str(err))

    def test_raise_on_error_mode(self):
        policy = make_policy()
        expected = make_expected(task_id="invalid-uuid")
        evidence = make_evidence()

        # In default mode, fail-closed block is returned
        res = decide_recovery(policy, expected, evidence, 1005.0)
        self.assertEqual(res["action"], "block")
        self.assertEqual(res["code"], "malformed_expected")

        # In strict raise_on_error mode, RecoveryPolicyError is raised
        with self.assertRaises(RecoveryPolicyError) as cm:
            decide_recovery(policy, expected, evidence, 1005.0, raise_on_error=True)
        self.assertEqual(cm.exception.code, "malformed_expected")


if __name__ == "__main__":
    unittest.main()
