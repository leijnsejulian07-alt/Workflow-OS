from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from workflow_os.durable_publication_worker import execute_bound_publication_job
from workflow_os.durable_side_effect_binding import DurableSideEffectBindingLedger
from workflow_os.durable_worker import VerifiedLeasedOpportunityJob
from workflow_os.job_queue import JobQueue
from workflow_os.production_reservation_pipeline import PreparedProductionSubmission
from workflow_os.side_effects import SideEffectLedger


NOW = "2026-08-22T23:00:00+00:00"


class DurablePublicationWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.queue = JobQueue(root / "jobs.sqlite")
        self.effects = SideEffectLedger(root / "effects.sqlite")
        self.bindings = DurableSideEffectBindingLedger(root / "bindings.sqlite")
        queued = self.queue.enqueue(
            idempotency_key="job-1",
            opportunity_id="opp-1",
            job_type="produce_and_publish",
            payload={"opportunity_id": "opp-1"},
            available_at=NOW,
            max_attempts=3,
        )
        leased = self.queue.claim(worker_id="worker-1", now=NOW, lease_seconds=300)
        self.assertIsNotNone(leased)
        self.job = leased or queued
        self.verified_job = VerifiedLeasedOpportunityJob(
            job=self.job,
            payload={"opportunity_id": "opp-1"},
            opportunity={"id": "opp-1"},
        )
        effect = self.effects.reserve(
            idempotency_key="publish-1",
            action="publish_submission",
            target="https://www.tiktok.com/",
            payload={"opportunity_id": "opp-1"},
            max_attempts=3,
        )
        prepared = object.__new__(PreparedProductionSubmission)
        object.__setattr__(prepared, "verified", None)
        object.__setattr__(
            prepared,
            "request",
            SimpleNamespace(opportunity_id="opp-1", destination_url="https://www.tiktok.com/"),
        )
        object.__setattr__(
            prepared,
            "reservation",
            SimpleNamespace(
                decision=SimpleNamespace(allowed=True, idempotency_key=effect.idempotency_key),
                side_effect=effect,
            ),
        )
        self.prepared = prepared

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, executor):
        return execute_bound_publication_job(
            self.verified_job,
            self.prepared,
            queue=self.queue,
            worker_id="worker-1",
            now=NOW,
            binding_ledger=self.bindings,
            side_effect_ledger=self.effects,
            execute_publication=executor,
        )

    def test_confirmed_success_completes_durable_job(self):
        def executor(_prepared):
            self.effects.begin_attempt("publish-1")
            return self.effects.mark_succeeded("publish-1", external_reference="post-1")

        result = self._run(executor)
        self.assertEqual("SUCCEEDED", result.side_effect.state)
        self.assertEqual("SUCCEEDED", result.job.state)
        self.assertEqual("publish-1", result.binding.side_effect_idempotency_key)

    def test_proven_not_applied_becomes_retryable_job(self):
        def executor(_prepared):
            self.effects.begin_attempt("publish-1")
            return self.effects.mark_failed("publish-1", definitely_not_applied=True)

        result = self._run(executor)
        self.assertEqual("FAILED_RETRYABLE", result.side_effect.state)
        self.assertEqual("FAILED_RETRYABLE", result.job.state)

    def test_ambiguous_platform_outcome_makes_job_unknown(self):
        def executor(_prepared):
            self.effects.begin_attempt("publish-1")
            return self.effects.mark_failed("publish-1", definitely_not_applied=False)

        result = self._run(executor)
        self.assertEqual("UNKNOWN", result.side_effect.state)
        self.assertEqual("UNKNOWN", result.job.state)

    def test_exception_before_side_effect_execution_is_retry_safe(self):
        def executor(_prepared):
            raise RuntimeError("credential unavailable before dispatch")

        result = self._run(executor)
        self.assertEqual("RESERVED", result.side_effect.state)
        self.assertEqual("FAILED_RETRYABLE", result.job.state)

    def test_exception_after_execution_started_never_blindly_retries(self):
        def executor(_prepared):
            self.effects.begin_attempt("publish-1")
            raise RuntimeError("worker crashed after dispatch")

        result = self._run(executor)
        self.assertEqual("EXECUTING", result.side_effect.state)
        self.assertEqual("UNKNOWN", result.job.state)

    def test_binding_is_persisted_before_executor_runs(self):
        observed = []

        def executor(_prepared):
            observed.append(self.bindings.get(self.job.job_id))
            self.effects.begin_attempt("publish-1")
            return self.effects.mark_succeeded("publish-1", external_reference="post-2")

        result = self._run(executor)
        self.assertIsNotNone(observed[0])
        self.assertEqual(result.binding, observed[0])


if __name__ == "__main__":
    unittest.main()
