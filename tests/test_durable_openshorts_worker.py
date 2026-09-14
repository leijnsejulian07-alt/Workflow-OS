from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workflow_os.durable_openshorts_worker import execute_prepared_durable_openshorts_job
from workflow_os.durable_worker import VerifiedLeasedOpportunityJob
from workflow_os.job_queue import JobQueue
from workflow_os.openshorts_execution import OpenShortsDispatchBinding
from workflow_os.openshorts_job_preparation import prepare_durable_openshorts_processing
from workflow_os.side_effects import SideEffectLedger


NOW = "2026-09-14T09:00:00+00:00"


class DurableOpenShortsWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.queue = JobQueue(root / "jobs.sqlite")
        self.effects = SideEffectLedger(root / "effects.sqlite")
        payload = {
            "opportunity_id": "opp-openshorts-1",
            "batch_fingerprint": "b" * 64,
            "batch_slot": 1,
            "opportunity_snapshot": {"opportunity_id": "opp-openshorts-1"},
            "opportunity_snapshot_sha256": "c" * 64,
            "revenue_control": {
                "opportunity_id": "opp-openshorts-1",
                "may_schedule": True,
            },
        }
        self.queue.enqueue(
            idempotency_key="job-openshorts-1",
            opportunity_id="opp-openshorts-1",
            job_type="produce_and_publish",
            payload=payload,
            available_at=NOW,
            max_attempts=3,
        )
        leased = self.queue.claim(worker_id="worker-1", now=NOW, lease_seconds=300)
        self.assertIsNotNone(leased)
        self.job = leased
        self.opportunity = {
            "opportunity_id": "opp-openshorts-1",
            "rights_verification_state": "VERIFIED",
            "usage_rights": "licensed campaign assets",
            "expected_owner_minutes": 0.0,
            "expected_net_profit": 12.5,
        }
        self.verified = VerifiedLeasedOpportunityJob(
            job=self.job,
            payload=payload,
            opportunity=self.opportunity,
        )
        self.prepared = prepare_durable_openshorts_processing(
            self.verified,
            source_url="https://youtu.be/abc",
            webhook_url="https://hooks.example.com/openshorts",
            credential_authority_verified=True,
            cost_authority_verified=True,
            ledger=self.effects,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, executor):
        return execute_prepared_durable_openshorts_job(
            self.verified,
            self.prepared,
            queue=self.queue,
            worker_id="worker-1",
            now=NOW,
            side_effect_ledger=self.effects,
            execute_dispatch=executor,
        )

    def test_confirmed_dispatch_completes_durable_job(self) -> None:
        key = self.prepared.reservation.idempotency_key

        def executor(_prepared):
            self.effects.begin_attempt(key)
            self.effects.mark_succeeded(key, external_reference="os-job-123")
            return OpenShortsDispatchBinding(key, "os-job-123", "d" * 64)

        result = self._run(executor)
        self.assertEqual("SUCCEEDED", result.side_effect.state)
        self.assertEqual("SUCCEEDED", result.job.state)
        self.assertEqual("os-job-123", result.side_effect.external_reference)

    def test_proven_not_applied_becomes_retryable_job(self) -> None:
        key = self.prepared.reservation.idempotency_key

        def executor(_prepared):
            self.effects.begin_attempt(key)
            self.effects.mark_failed(key, definitely_not_applied=True)
            raise RuntimeError("provider rejected before accepting work")

        result = self._run(executor)
        self.assertEqual("FAILED_RETRYABLE", result.side_effect.state)
        self.assertEqual("FAILED_RETRYABLE", result.job.state)

    def test_ambiguous_dispatch_makes_job_unknown(self) -> None:
        key = self.prepared.reservation.idempotency_key

        def executor(_prepared):
            self.effects.begin_attempt(key)
            self.effects.mark_failed(key, definitely_not_applied=False)
            raise RuntimeError("response was ambiguous")

        result = self._run(executor)
        self.assertEqual("UNKNOWN", result.side_effect.state)
        self.assertEqual("UNKNOWN", result.job.state)

    def test_exception_before_external_execution_is_retry_safe(self) -> None:
        def executor(_prepared):
            raise RuntimeError("credential provider unavailable")

        result = self._run(executor)
        self.assertEqual("RESERVED", result.side_effect.state)
        self.assertEqual("FAILED_RETRYABLE", result.job.state)

    def test_exception_after_execution_started_never_blindly_retries(self) -> None:
        key = self.prepared.reservation.idempotency_key

        def executor(_prepared):
            self.effects.begin_attempt(key)
            raise RuntimeError("worker crashed after dispatch started")

        result = self._run(executor)
        self.assertEqual("EXECUTING", result.side_effect.state)
        self.assertEqual("UNKNOWN", result.job.state)

    def test_existing_confirmed_dispatch_completes_without_redispatch(self) -> None:
        key = self.prepared.reservation.idempotency_key
        self.effects.begin_attempt(key)
        self.effects.mark_succeeded(key, external_reference="os-job-existing")
        calls = []

        def executor(_prepared):
            calls.append(True)
            raise AssertionError("confirmed dispatch must not be repeated")

        result = self._run(executor)
        self.assertEqual([], calls)
        self.assertEqual("SUCCEEDED", result.side_effect.state)
        self.assertEqual("SUCCEEDED", result.job.state)


if __name__ == "__main__":
    unittest.main()
