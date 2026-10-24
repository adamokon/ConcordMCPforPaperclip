"""
Adversarial unit tests for authenticated pre-provider evidence decoder.
ConcordMCPforPaperclip automated recovery telemetry decoder.
"""

from __future__ import annotations

import json
import unittest
from typing import Any, Dict, Tuple

from concord_paperclip.recovery_evidence import RecoveryEvidenceError, derive_evidence


def _make_valid_fixtures() -> Tuple[
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    Dict[str, Any],
    float,
]:
    """Create valid baseline inputs for evidence derivation."""
    task_id = "11111111-1111-4111-8111-111111111111"
    issue_id = "22222222-2222-4222-8222-222222222222"
    agent_id = "33333333-3333-4333-8333-333333333333"
    source_run_id = "44444444-4444-4444-8444-444444444444"
    attempt_id = "55555555-5555-4555-8555-555555555555"
    company_id = "66666666-6666-4666-8666-666666666666"
    project_id = "77777777-7777-4777-8777-777777777777"

    expected = {
        "task_id": task_id,
        "issue_id": issue_id,
        "agent_id": agent_id,
        "source_run_id": source_run_id,
        "attempt_id": attempt_id,
        "company_id": company_id,
        "project_id": project_id,
        "repo": "concord/paperclip-core",
        "retries_used": 0,
    }

    producer_hash = "a" * 64
    producer = {
        "expected_command": "concord-agent-runner --mode pre-provider",
        "expected_sha256": producer_hash,
        "actual_sha256": producer_hash,
        "exit_code": 75,
    }

    worker = {
        "environment_removed": True,
        "workspace_absent": True,
    }

    stdout_payload = {
        "kind": "concord.pre_provider_failure.v1",
        "task_id": task_id,
        "issue_id": issue_id,
        "agent_id": agent_id,
        "company_id": company_id,
        "project_id": project_id,
        "run_id": source_run_id,
        "producer_sha256": producer_hash,
        "error_kind": "pre_provider_transient",
    }

    native = {
        "issue": {
            "id": issue_id,
            "companyId": company_id,
            "projectId": project_id,
            "assigneeAgentId": agent_id,
            "status": "todo",
            "executionRunId": None,
            "checkoutRunId": None,
        },
        "agent": {
            "id": agent_id,
            "status": "idle",
            "pauseReason": None,
            "adapterType": "process",
            "command": "concord-agent-runner --mode pre-provider",
        },
        "run": {
            "id": source_run_id,
            "companyId": company_id,
            "agentId": agent_id,
            "status": "failed",
            "exitCode": 75,
            "resultJson": {
                "stdout": json.dumps(stdout_payload),
            },
        },
        "recovery_action_id": None,
        "successors": [],
        "other_active_runs": [],
    }

    now = 1729800000.0
    return expected, native, worker, producer, now


class TestRecoveryEvidence(unittest.TestCase):
    """Test suite for recovery evidence decoder."""

    def test_valid_native_failure_proof(self) -> None:
        """Valid pre-provider transient failure proof should grant trusted attestation."""
        expected, native, worker, producer, now = _make_valid_fixtures()
        evidence = derive_evidence(expected, native, worker, producer, now)

        self.assertEqual(evidence["task_id"], expected["task_id"])
        self.assertEqual(evidence["issue_id"], expected["issue_id"])
        self.assertEqual(evidence["agent_id"], expected["agent_id"])
        self.assertEqual(evidence["source_run_id"], expected["source_run_id"])
        self.assertEqual(evidence["attempt_id"], expected["attempt_id"])
        self.assertEqual(evidence["company_id"], expected["company_id"])
        self.assertEqual(evidence["project_id"], expected["project_id"])
        self.assertEqual(evidence["observed_at"], now)
        self.assertEqual(evidence["native_status"], "failed")
        self.assertIs(evidence["cleanup_complete"], True)
        self.assertIs(evidence["other_run_active"], False)
        self.assertIs(evidence["provider_started"], False)
        self.assertEqual(evidence["effects"], "not_performed")
        self.assertEqual(evidence["attestation"], "trusted_pre_provider_v1")
        self.assertEqual(evidence["error_kind"], "pre_provider_transient")
        self.assertIs(evidence["paused"], False)
        self.assertIs(evidence["terminated"], False)
        self.assertIsNone(evidence["recovery_action_id"])
        self.assertIsNone(evidence["new_run"])

    def test_foreign_identities_in_native(self) -> None:
        """Mismatched scope identities in native telemetry must raise RecoveryEvidenceError."""
        foreign_uuid = "ffffffff-ffff-4fff-8fff-ffffffffffff"

        # Foreign issue id
        expected, native, worker, producer, now = _make_valid_fixtures()
        native["issue"]["id"] = foreign_uuid
        with self.assertRaises(RecoveryEvidenceError) as ctx:
            derive_evidence(expected, native, worker, producer, now)
        self.assertEqual(ctx.exception.code, "scope_violation")

        # Foreign issue companyId
        expected, native, worker, producer, now = _make_valid_fixtures()
        native["issue"]["companyId"] = foreign_uuid
        with self.assertRaises(RecoveryEvidenceError) as ctx:
            derive_evidence(expected, native, worker, producer, now)
        self.assertEqual(ctx.exception.code, "scope_violation")

        # Foreign issue projectId
        expected, native, worker, producer, now = _make_valid_fixtures()
        native["issue"]["projectId"] = foreign_uuid
        with self.assertRaises(RecoveryEvidenceError) as ctx:
            derive_evidence(expected, native, worker, producer, now)
        self.assertEqual(ctx.exception.code, "scope_violation")

        # Foreign issue assigneeAgentId
        expected, native, worker, producer, now = _make_valid_fixtures()
        native["issue"]["assigneeAgentId"] = foreign_uuid
        with self.assertRaises(RecoveryEvidenceError) as ctx:
            derive_evidence(expected, native, worker, producer, now)
        self.assertEqual(ctx.exception.code, "scope_violation")

        # Foreign agent id
        expected, native, worker, producer, now = _make_valid_fixtures()
        native["agent"]["id"] = foreign_uuid
        with self.assertRaises(RecoveryEvidenceError) as ctx:
            derive_evidence(expected, native, worker, producer, now)
        self.assertEqual(ctx.exception.code, "scope_violation")

        # Foreign run id
        expected, native, worker, producer, now = _make_valid_fixtures()
        native["run"]["id"] = foreign_uuid
        with self.assertRaises(RecoveryEvidenceError) as ctx:
            derive_evidence(expected, native, worker, producer, now)
        self.assertEqual(ctx.exception.code, "scope_violation")

        # Foreign run companyId
        expected, native, worker, producer, now = _make_valid_fixtures()
        native["run"]["companyId"] = foreign_uuid
        with self.assertRaises(RecoveryEvidenceError) as ctx:
            derive_evidence(expected, native, worker, producer, now)
        self.assertEqual(ctx.exception.code, "scope_violation")

        # Foreign run agentId
        expected, native, worker, producer, now = _make_valid_fixtures()
        native["run"]["agentId"] = foreign_uuid
        with self.assertRaises(RecoveryEvidenceError) as ctx:
            derive_evidence(expected, native, worker, producer, now)
        self.assertEqual(ctx.exception.code, "scope_violation")

    def test_foreign_identities_in_stdout(self) -> None:
        """Foreign identity inside stdout JSON must not produce attestation."""
        foreign_uuid = "ffffffff-ffff-4fff-8fff-ffffffffffff"

        for field in ("task_id", "issue_id", "agent_id", "company_id", "project_id", "run_id"):
            expected, native, worker, producer, now = _make_valid_fixtures()
            stdout_dict = json.loads(native["run"]["resultJson"]["stdout"])
            stdout_dict[field] = foreign_uuid
            native["run"]["resultJson"]["stdout"] = json.dumps(stdout_dict)

            evidence = derive_evidence(expected, native, worker, producer, now)
            self.assertIsNone(evidence["attestation"])
            self.assertEqual(evidence["effects"], "unknown")
            self.assertEqual(evidence["error_kind"], "unknown")
            self.assertIsNone(evidence["provider_started"])

    def test_foreign_producer_hashes(self) -> None:
        """Producer SHA mismatch or foreign hash in stdout must reject attestation."""
        # Producer actual_sha256 != expected_sha256
        expected, native, worker, producer, now = _make_valid_fixtures()
        producer["actual_sha256"] = "b" * 64
        evidence = derive_evidence(expected, native, worker, producer, now)
        self.assertIsNone(evidence["attestation"])
        self.assertEqual(evidence["effects"], "unknown")

        # Stdout producer_sha256 != expected_sha256
        expected, native, worker, producer, now = _make_valid_fixtures()
        stdout_dict = json.loads(native["run"]["resultJson"]["stdout"])
        stdout_dict["producer_sha256"] = "c" * 64
        native["run"]["resultJson"]["stdout"] = json.dumps(stdout_dict)
        evidence = derive_evidence(expected, native, worker, producer, now)
        self.assertIsNone(evidence["attestation"])
        self.assertEqual(evidence["effects"], "unknown")

    def test_foreign_or_mismatched_command_and_adapter(self) -> None:
        """Agent adapterType != 'process' or command mismatch must reject attestation."""
        # Non-process adapter (e.g. docker)
        expected, native, worker, producer, now = _make_valid_fixtures()
        native["agent"]["adapterType"] = "docker"
        evidence = derive_evidence(expected, native, worker, producer, now)
        self.assertIsNone(evidence["attestation"])
        self.assertEqual(evidence["effects"], "unknown")

        # Mismatched command
        expected, native, worker, producer, now = _make_valid_fixtures()
        native["agent"]["command"] = "wrong-command"
        evidence = derive_evidence(expected, native, worker, producer, now)
        self.assertIsNone(evidence["attestation"])
        self.assertEqual(evidence["effects"], "unknown")

    def test_output_marker_nested_in_model_prose(self) -> None:
        """Attestation marker embedded in model prose or extra data must be rejected."""
        expected, native, worker, producer, now = _make_valid_fixtures()
        valid_json = native["run"]["resultJson"]["stdout"]

        # Leading model prose
        native["run"]["resultJson"]["stdout"] = f"Error details:\n{valid_json}"
        evidence = derive_evidence(expected, native, worker, producer, now)
        self.assertIsNone(evidence["attestation"])
        self.assertEqual(evidence["effects"], "unknown")

        # Trailing model prose
        native["run"]["resultJson"]["stdout"] = f"{valid_json}\nPlease retry the command."
        evidence = derive_evidence(expected, native, worker, producer, now)
        self.assertIsNone(evidence["attestation"])
        self.assertEqual(evidence["effects"], "unknown")

        # Multiple JSON objects
        native["run"]["resultJson"]["stdout"] = f"{valid_json}{valid_json}"
        evidence = derive_evidence(expected, native, worker, producer, now)
        self.assertIsNone(evidence["attestation"])
        self.assertEqual(evidence["effects"], "unknown")

    def test_extra_keys_in_stdout(self) -> None:
        """Extra keys injected into stdout JSON must reject attestation."""
        expected, native, worker, producer, now = _make_valid_fixtures()
        stdout_dict = json.loads(native["run"]["resultJson"]["stdout"])
        stdout_dict["injected_field"] = "exploit"
        native["run"]["resultJson"]["stdout"] = json.dumps(stdout_dict)

        evidence = derive_evidence(expected, native, worker, producer, now)
        self.assertIsNone(evidence["attestation"])
        self.assertEqual(evidence["effects"], "unknown")

    def test_wrong_exitcode_and_bool_traps(self) -> None:
        """Wrong exit code (e.g. exit 1, 0, 74) or bool values must reject attestation."""
        for bad_code in (1, 0, 74, 76, True, False, 75.0, None):
            expected, native, worker, producer, now = _make_valid_fixtures()
            native["run"]["exitCode"] = bad_code
            evidence = derive_evidence(expected, native, worker, producer, now)
            self.assertIsNone(evidence["attestation"])
            self.assertEqual(evidence["effects"], "unknown")

    def test_malformed_nonfinite_unhashable_fields(self) -> None:
        """Malformed, non-finite, or unhashable inputs must raise RecoveryEvidenceError."""
        # Non-finite now
        expected, native, worker, producer, now = _make_valid_fixtures()
        with self.assertRaises(RecoveryEvidenceError):
            derive_evidence(expected, native, worker, producer, float("nan"))
        with self.assertRaises(RecoveryEvidenceError):
            derive_evidence(expected, native, worker, producer, float("inf"))
        with self.assertRaises(RecoveryEvidenceError):
            derive_evidence(expected, native, worker, producer, True)

        # Non-canonical UUID in expected
        expected, native, worker, producer, now = _make_valid_fixtures()
        expected["task_id"] = "not-a-uuid"
        with self.assertRaises(RecoveryEvidenceError):
            derive_evidence(expected, native, worker, producer, now)

        expected, native, worker, producer, now = _make_valid_fixtures()
        expected["task_id"] = "11111111-1111-4111-8111-11111111111G"
        with self.assertRaises(RecoveryEvidenceError):
            derive_evidence(expected, native, worker, producer, now)

        # Uppercase UUID rejected (must be canonical lowercase)
        expected, native, worker, producer, now = _make_valid_fixtures()
        expected["task_id"] = "11111111-1111-4111-8111-11111111111A"
        with self.assertRaises(RecoveryEvidenceError):
            derive_evidence(expected, native, worker, producer, now)

        # Unhashable object for UUID
        expected, native, worker, producer, now = _make_valid_fixtures()
        expected["task_id"] = {}
        with self.assertRaises(RecoveryEvidenceError):
            derive_evidence(expected, native, worker, producer, now)

        # Invalid retries_used
        expected, native, worker, producer, now = _make_valid_fixtures()
        expected["retries_used"] = True  # strict int, not bool
        with self.assertRaises(RecoveryEvidenceError):
            derive_evidence(expected, native, worker, producer, now)

        expected, native, worker, producer, now = _make_valid_fixtures()
        expected["retries_used"] = -1
        with self.assertRaises(RecoveryEvidenceError):
            derive_evidence(expected, native, worker, producer, now)

        # Producer malformed
        expected, native, worker, producer, now = _make_valid_fixtures()
        producer["expected_command"] = ""
        with self.assertRaises(RecoveryEvidenceError):
            derive_evidence(expected, native, worker, producer, now)

        expected, native, worker, producer, now = _make_valid_fixtures()
        producer["expected_sha256"] = "invalid_hash"
        with self.assertRaises(RecoveryEvidenceError):
            derive_evidence(expected, native, worker, producer, now)

        expected, native, worker, producer, now = _make_valid_fixtures()
        producer["exit_code"] = 74
        with self.assertRaises(RecoveryEvidenceError):
            derive_evidence(expected, native, worker, producer, now)

        # Worker non-bool flags
        expected, native, worker, producer, now = _make_valid_fixtures()
        worker["environment_removed"] = 1  # not strict bool
        with self.assertRaises(RecoveryEvidenceError):
            derive_evidence(expected, native, worker, producer, now)

        expected, native, worker, producer, now = _make_valid_fixtures()
        worker["workspace_absent"] = "true"  # not strict bool
        with self.assertRaises(RecoveryEvidenceError):
            derive_evidence(expected, native, worker, producer, now)

        # Invalid enum statuses
        expected, native, worker, producer, now = _make_valid_fixtures()
        native["issue"]["status"] = "invalid_issue_status"
        with self.assertRaises(RecoveryEvidenceError):
            derive_evidence(expected, native, worker, producer, now)

        expected, native, worker, producer, now = _make_valid_fixtures()
        native["agent"]["status"] = "invalid_agent_status"
        with self.assertRaises(RecoveryEvidenceError):
            derive_evidence(expected, native, worker, producer, now)

        expected, native, worker, producer, now = _make_valid_fixtures()
        native["run"]["status"] = "invalid_run_status"
        with self.assertRaises(RecoveryEvidenceError):
            derive_evidence(expected, native, worker, producer, now)

    def test_provider_or_workspace_evidence_unknown(self) -> None:
        """If workspace is not absent or environment not removed, proof must fail."""
        # Workspace still exists
        expected, native, worker, producer, now = _make_valid_fixtures()
        worker["workspace_absent"] = False
        evidence = derive_evidence(expected, native, worker, producer, now)
        self.assertIsNone(evidence["attestation"])
        self.assertEqual(evidence["effects"], "unknown")
        self.assertEqual(evidence["error_kind"], "unknown")

        # Environment not removed
        expected, native, worker, producer, now = _make_valid_fixtures()
        worker["environment_removed"] = False
        evidence = derive_evidence(expected, native, worker, producer, now)
        self.assertIsNone(evidence["attestation"])
        self.assertEqual(evidence["effects"], "unknown")
        self.assertIs(evidence["cleanup_complete"], False)

    def test_native_success_no_new_execution(self) -> None:
        """Native run status 'succeeded' sets trusted worker result without new execution."""
        expected, native, worker, producer, now = _make_valid_fixtures()
        native["run"]["status"] = "succeeded"
        native["run"]["exitCode"] = 0
        native["run"]["resultJson"] = {"stdout": "success output"}

        evidence = derive_evidence(expected, native, worker, producer, now)
        self.assertIs(evidence["provider_started"], True)
        self.assertEqual(evidence["effects"], "completed")
        self.assertEqual(evidence["attestation"], "trusted_worker_result_v1")
        self.assertIsNone(evidence["error_kind"])
        self.assertEqual(evidence["native_status"], "succeeded")
        self.assertIsNone(evidence["new_run"])

    def test_busy_unrelated_run(self) -> None:
        """Active runs other than an adopted successor must set other_run_active=True."""
        unrelated_run_id = "99999999-9999-4999-8999-999999999999"

        # No successor, but unrelated run active
        expected, native, worker, producer, now = _make_valid_fixtures()
        native["other_active_runs"] = [{"id": unrelated_run_id}]
        evidence = derive_evidence(expected, native, worker, producer, now)
        self.assertIs(evidence["other_run_active"], True)

        # Empty active runs -> False
        expected, native, worker, producer, now = _make_valid_fixtures()
        native["other_active_runs"] = []
        evidence = derive_evidence(expected, native, worker, producer, now)
        self.assertIs(evidence["other_run_active"], False)

    def test_exact_successor_adoption(self) -> None:
        """Exactly one validated successor matching recovery_action_id must be adopted."""
        recovery_action_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        succ_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

        expected, native, worker, producer, now = _make_valid_fixtures()
        native["recovery_action_id"] = recovery_action_id
        native["successors"] = [
            {
                "id": succ_id,
                "companyId": expected["company_id"],
                "agentId": expected["agent_id"],
                "status": "queued",
                "contextSnapshot": {
                    "issueId": expected["issue_id"],
                    "recoveryActionId": recovery_action_id,
                },
            }
        ]
        # When adopted successor is in other_active_runs, it is excluded
        native["other_active_runs"] = [{"id": succ_id}]

        evidence = derive_evidence(expected, native, worker, producer, now)
        self.assertIsNotNone(evidence["new_run"])
        self.assertEqual(evidence["new_run"]["id"], succ_id)
        self.assertEqual(evidence["new_run"]["status"], "queued")
        self.assertEqual(evidence["new_run"]["task_id"], expected["task_id"])
        self.assertEqual(evidence["new_run"]["issue_id"], expected["issue_id"])
        self.assertEqual(evidence["new_run"]["agent_id"], expected["agent_id"])
        self.assertEqual(evidence["new_run"]["company_id"], expected["company_id"])
        self.assertEqual(evidence["new_run"]["project_id"], expected["project_id"])
        self.assertEqual(evidence["new_run"]["source_run_id"], expected["source_run_id"])
        self.assertEqual(evidence["new_run"]["recovery_action_id"], recovery_action_id)
        self.assertIs(evidence["other_run_active"], False)

        # If another run is also active, other_run_active becomes True
        native["other_active_runs"] = [
            {"id": succ_id},
            {"id": "99999999-9999-4999-8999-999999999999"},
        ]
        evidence = derive_evidence(expected, native, worker, producer, now)
        self.assertIs(evidence["other_run_active"], True)

    def test_ambiguous_siblings_error(self) -> None:
        """Multiple successors claiming the same recoveryActionId must raise an error."""
        recovery_action_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

        expected, native, worker, producer, now = _make_valid_fixtures()
        native["recovery_action_id"] = recovery_action_id
        native["successors"] = [
            {
                "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "companyId": expected["company_id"],
                "agentId": expected["agent_id"],
                "status": "queued",
                "contextSnapshot": {
                    "issueId": expected["issue_id"],
                    "recoveryActionId": recovery_action_id,
                },
            },
            {
                "id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                "companyId": expected["company_id"],
                "agentId": expected["agent_id"],
                "status": "running",
                "contextSnapshot": {
                    "issueId": expected["issue_id"],
                    "recoveryActionId": recovery_action_id,
                },
            },
        ]

        with self.assertRaises(RecoveryEvidenceError) as ctx:
            derive_evidence(expected, native, worker, producer, now)
        self.assertEqual(ctx.exception.code, "ambiguous_successor")

    def test_successor_scope_isolation(self) -> None:
        """Successor reusing source_run_id or mismatching scope must raise error."""
        recovery_action_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        foreign_uuid = "ffffffff-ffff-4fff-8fff-ffffffffffff"

        # Reusing source_run_id
        expected, native, worker, producer, now = _make_valid_fixtures()
        native["recovery_action_id"] = recovery_action_id
        native["successors"] = [
            {
                "id": expected["source_run_id"],
                "companyId": expected["company_id"],
                "agentId": expected["agent_id"],
                "status": "queued",
                "contextSnapshot": {
                    "issueId": expected["issue_id"],
                    "recoveryActionId": recovery_action_id,
                },
            }
        ]
        with self.assertRaises(RecoveryEvidenceError) as ctx:
            derive_evidence(expected, native, worker, producer, now)
        self.assertEqual(ctx.exception.code, "scope_violation")

        # Foreign companyId
        expected, native, worker, producer, now = _make_valid_fixtures()
        native["recovery_action_id"] = recovery_action_id
        native["successors"] = [
            {
                "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "companyId": foreign_uuid,
                "agentId": expected["agent_id"],
                "status": "queued",
                "contextSnapshot": {
                    "issueId": expected["issue_id"],
                    "recoveryActionId": recovery_action_id,
                },
            }
        ]
        with self.assertRaises(RecoveryEvidenceError) as ctx:
            derive_evidence(expected, native, worker, producer, now)
        self.assertEqual(ctx.exception.code, "scope_violation")

        # Foreign agentId
        expected, native, worker, producer, now = _make_valid_fixtures()
        native["recovery_action_id"] = recovery_action_id
        native["successors"] = [
            {
                "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "companyId": expected["company_id"],
                "agentId": foreign_uuid,
                "status": "queued",
                "contextSnapshot": {
                    "issueId": expected["issue_id"],
                    "recoveryActionId": recovery_action_id,
                },
            }
        ]
        with self.assertRaises(RecoveryEvidenceError) as ctx:
            derive_evidence(expected, native, worker, producer, now)
        self.assertEqual(ctx.exception.code, "scope_violation")

        # Foreign issueId
        expected, native, worker, producer, now = _make_valid_fixtures()
        native["recovery_action_id"] = recovery_action_id
        native["successors"] = [
            {
                "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "companyId": expected["company_id"],
                "agentId": expected["agent_id"],
                "status": "queued",
                "contextSnapshot": {
                    "issueId": foreign_uuid,
                    "recoveryActionId": recovery_action_id,
                },
            }
        ]
        with self.assertRaises(RecoveryEvidenceError) as ctx:
            derive_evidence(expected, native, worker, producer, now)
        self.assertEqual(ctx.exception.code, "scope_violation")

        # Invalid successor status (e.g. failed)
        expected, native, worker, producer, now = _make_valid_fixtures()
        native["recovery_action_id"] = recovery_action_id
        native["successors"] = [
            {
                "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "companyId": expected["company_id"],
                "agentId": expected["agent_id"],
                "status": "failed",
                "contextSnapshot": {
                    "issueId": expected["issue_id"],
                    "recoveryActionId": recovery_action_id,
                },
            }
        ]
        with self.assertRaises(RecoveryEvidenceError) as ctx:
            derive_evidence(expected, native, worker, producer, now)
        self.assertEqual(ctx.exception.code, "invalid_status")

    def test_terminal_issue_security_refusal(self) -> None:
        """Terminal issue status ('done' or 'cancelled') must yield error_kind='security'."""
        for term_status in ("done", "cancelled"):
            expected, native, worker, producer, now = _make_valid_fixtures()
            native["issue"]["status"] = term_status
            evidence = derive_evidence(expected, native, worker, producer, now)

            self.assertEqual(evidence["error_kind"], "security")
            self.assertIsNone(evidence["attestation"])
            self.assertIsNone(evidence["provider_started"])
            self.assertEqual(evidence["effects"], "unknown")

    def test_agent_paused_and_terminated_flags(self) -> None:
        """Agent paused and terminated flags must reflect status and pauseReason strictly."""
        # Status paused
        expected, native, worker, producer, now = _make_valid_fixtures()
        native["agent"]["status"] = "paused"
        evidence = derive_evidence(expected, native, worker, producer, now)
        self.assertIs(evidence["paused"], True)
        self.assertIs(evidence["terminated"], False)

        # Status terminated
        expected, native, worker, producer, now = _make_valid_fixtures()
        native["agent"]["status"] = "terminated"
        evidence = derive_evidence(expected, native, worker, producer, now)
        self.assertIs(evidence["paused"], False)
        self.assertIs(evidence["terminated"], True)

        # Status active with pauseReason set
        expected, native, worker, producer, now = _make_valid_fixtures()
        native["agent"]["status"] = "active"
        native["agent"]["pauseReason"] = "refusal"
        evidence = derive_evidence(expected, native, worker, producer, now)
        self.assertIs(evidence["paused"], True)
        self.assertIs(evidence["terminated"], False)

        # Status active with empty/None pauseReason
        expected, native, worker, producer, now = _make_valid_fixtures()
        native["agent"]["status"] = "active"
        native["agent"]["pauseReason"] = None
        evidence = derive_evidence(expected, native, worker, producer, now)
        self.assertIs(evidence["paused"], False)
        self.assertIs(evidence["terminated"], False)

    def test_stdout_oversized(self) -> None:
        """Stdout payload exceeding 4096 UTF-8 bytes must not produce attestation."""
        expected, native, worker, producer, now = _make_valid_fixtures()
        large_comment = "x" * 4100
        native["run"]["resultJson"]["stdout"] = large_comment
        evidence = derive_evidence(expected, native, worker, producer, now)
        self.assertIsNone(evidence["attestation"])
        self.assertEqual(evidence["effects"], "unknown")

    def test_stdout_invalid_json_or_non_dict(self) -> None:
        """Non-JSON or non-dict stdout must not produce attestation."""
        for invalid_stdout in ("not a json string", "12345", "[1, 2, 3]", "true"):
            expected, native, worker, producer, now = _make_valid_fixtures()
            native["run"]["resultJson"]["stdout"] = invalid_stdout
            evidence = derive_evidence(expected, native, worker, producer, now)
            self.assertIsNone(evidence["attestation"])
            self.assertEqual(evidence["effects"], "unknown")


if __name__ == "__main__":
    unittest.main()
