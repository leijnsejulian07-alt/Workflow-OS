from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workflow_os.adapters.whop_bounty_execution import reserve_whop_bounty_submission
from workflow_os.adapters.whop_bounty_submission import (
    WhopBountyDeliverable,
    WhopBountySubmissionEvidence,
)
from workflow_os.durable_whop_bounty_binding import DurableWhopBountyBindingLedger
from workflow_os.durable_whop_bounty_worker import execute_bound_whop_bounty_job
from workflow_os.durable_worker import VerifiedLeasedOpportunityJob
from workflow_os.job_queue import JobQueue
from workflow_os.side_effects import SideEffectLedger


NOW = "2026-08-24T02:00:00+00:00"


class DurableWhopBountyWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.queue = JobQueue(root / "jobs.sqlite")
        self.effects = SideEffectLedger(root / "effects.sqlite")
        self.bindings = DurableWhopBountyBindingLedger(root / "bindings.sqlite")
        self.opportunity = {
            "opportunity_id": "opp-whop-1",
            "source_platform": "whop_bounties",
            "campaign_id": "bnty_example123",
            "bounty_type": "workforce",
            "machine_submission_verified": True,
        }
        self.queue.enqueue(
            idempotency_key="job-whop-1",
            opportunity_id="opp-whop-1",
            job_type="produce_and_publish",
            payload={"opportunity_id": "opp-whop-1", "campaign_id": "bnty_example123"},
            available_at=NOW,
            max_attempts=3,
        )
        leased = self.queue.claim(worker_id="worker-1", now=NOW, lease_seconds=300)
        self.assertIsNotNone(leased)
        self.job = leased
        self.verified_job = VerifiedLeasedOpportunityJob(
            job=self.job,
            payload={"opportunity_id": "opp-whop-1", "campaign_id": "bnty_example123"},
            opportunity=self.opportunity,
        )
        self.reservation = reserve_whop_bounty_submission(
            bounty_id="bnty_example123",
            deliverable=WhopBountyDeliverable(
                deliverable_type="content_url",
                urls=("https://example.com/work/123",),
                caption="verified deliverable",
            ),
            evidence=WhopBountySubmissionEvidence(
                user_credential_verified=True,
                worker_identity_verified=True,
                rights_verified=True,
                campaign_requirements_verified=True,
                deliverable_verified=True,
            ),
            idempotency_key="whop-bounty:job-0001",
            ledger=self.effects,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, executor):
        return execute_bound_whop_bounty_job(
            self.verified_job,
            self.reservation,
            queue=self.queue,
            worker_id="worker-1",
            now=NOW,
            binding_ledger=self.bindings,
            side_effect_ledger=self.effects,
            execute_submission=executor,
        )

    def test_confirmed_submission_completes_durable_job(self):
        def executor(_reservation):
            self.effects.begin_attempt("whop-bounty:job-0001")
            return self.effects.mark_succeeded(
                "whop-bounty:job-0001",
                external_reference="btys_submission123",
            )

        result = self._run(executor)
        self.assertEqual("SUCCEEDED", result.side_effect.state)
        self.assertEqual("SUCCEEDED", result.job.state)
        self.assertEqual("bnty_example123", result.binding.bounty_id)

    def test_proven_not_applied_becomes_retryable_job(self):
        def executor(_reservation):
            self.effects.begin_attempt("whop-bounty:job-0001")
            return self.effects.mark_failed(
                "whop-bounty:job-0001",
                definitely_not_applied=True,
            )

        result = self._run(executor)
        self.assertEqual("FAILED_RETRYABLE", result.side_effect.state)
        self.assertEqual("FAILED_RETRYABLE", result.job.state)

    def test_ambiguous_submission_makes_job_unknown(self):
        def executor(_reservation):
            self.effects.begin_attempt("whop-bounty:job-0001")
            return self.effects.mark_failed(
                "whop-bounty:job-0001",
                definitely_not_applied=False,
            )

        result = self._run(executor)
        self.assertEqual("UNKNOWN", result.side_effect.state)
        self.assertEqual("UNKNOWN", result.job.state)

    def test_exception_before_external_execution_is_retry_safe(self):
        def executor(_reservation):
            raise RuntimeError("credential provider unavailable")

        result = self._run(executor)
        self.assertEqual("RESERVED", result.side_effect.state)
        self.assertEqual("FAILED_RETRYABLE", result.job.state)

    def test_exception_after_execution_started_never_blindly_retries(self):
        def executor(_reservation):
            self.effects.begin_attempt("whop-bounty:job-0001")
            raise RuntimeError("worker crashed after dispatch")

        result = self._run(executor)
        self.assertEqual("EXECUTING", result.side_effect.state)
        self.assertEqual("UNKNOWN", result.job.state)

    def test_binding_exists_before_executor_runs(self):
        observed = []

        def executor(_reservation):
            observed.append(self.bindings.get(self.job.job_id))
            self.effects.begin_attempt("whop-bounty:job-0001")
            return self.effects.mark_succeeded(
                "whop-bounty:job-0001",
                external_reference="btys_submission456",
            )

        result = self._run(executor)
        self.assertIsNotNone(observed[0])
        self.assertEqual(result.binding, observed[0])

    def test_wrong_returned_side_effect_cannot_complete_job(self):
        other = self.effects.reserve(
            idempotency_key="other-effect",
            action="submit_whop_bounty",
            target="https://api.whop.com/api/v1/bounty_submissions",
            payload={"bounty_id": "bnty_other123"},
            max_attempts=3,
        )

        def executor(_reservation):
            return other

        result = self._run(executor)
        self.assertEqual("RESERVED", result.side_effect.state)
        self.assertEqual("FAILED_RETRYABLE", result.job.state)


if __name__ == "__main__":
    unittest.main()
