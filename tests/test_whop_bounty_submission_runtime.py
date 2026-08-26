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
from workflow_os.durable_worker import VerifiedLeasedOpportunityJob
from workflow_os.job_queue import JobQueue
from workflow_os.side_effects import SideEffectLedger
from workflow_os.whop_bounty_submission_provenance import WhopBountySubmissionProvenanceLedger
from workflow_os.whop_bounty_submission_runtime import execute_whop_bounty_job_and_record_provenance


NOW = "2026-08-26T02:00:00+00:00"


class WhopBountySubmissionRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.queue = JobQueue(root / "jobs.sqlite")
        self.effects = SideEffectLedger(root / "effects.sqlite")
        self.bindings = DurableWhopBountyBindingLedger(root / "bindings.sqlite")
        self.provenance = WhopBountySubmissionProvenanceLedger(root / "provenance.sqlite")
        self.opportunity = {
            "opportunity_id": "opp-whop-runtime-1",
            "source_platform": "whop_bounties",
            "campaign_id": "bnty_runtime123",
            "bounty_type": "workforce",
            "machine_submission_verified": True,
        }
        self.queue.enqueue(
            idempotency_key="job-whop-runtime-1",
            opportunity_id="opp-whop-runtime-1",
            job_type="produce_and_publish",
            payload={"opportunity_id": "opp-whop-runtime-1", "campaign_id": "bnty_runtime123"},
            available_at=NOW,
            max_attempts=3,
        )
        leased = self.queue.claim(worker_id="worker-runtime-1", now=NOW, lease_seconds=300)
        self.assertIsNotNone(leased)
        self.verified_job = VerifiedLeasedOpportunityJob(
            job=leased,
            payload={"opportunity_id": "opp-whop-runtime-1", "campaign_id": "bnty_runtime123"},
            opportunity=self.opportunity,
        )
        self.reservation = reserve_whop_bounty_submission(
            bounty_id="bnty_runtime123",
            deliverable=WhopBountyDeliverable(
                deliverable_type="content_url",
                urls=("https://example.com/work/runtime-1",),
                caption="verified runtime deliverable",
            ),
            evidence=WhopBountySubmissionEvidence(
                user_credential_verified=True,
                worker_identity_verified=True,
                rights_verified=True,
                campaign_requirements_verified=True,
                deliverable_verified=True,
            ),
            idempotency_key="whop-bounty:runtime-0001",
            ledger=self.effects,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, executor):
        return execute_whop_bounty_job_and_record_provenance(
            self.verified_job,
            self.reservation,
            queue=self.queue,
            worker_id="worker-runtime-1",
            now=NOW,
            binding_ledger=self.bindings,
            side_effect_ledger=self.effects,
            provenance_ledger=self.provenance,
            execute_submission=executor,
        )

    def test_confirmed_submission_records_payout_attribution_provenance(self):
        def executor(_reservation):
            self.effects.begin_attempt("whop-bounty:runtime-0001")
            return self.effects.mark_succeeded(
                "whop-bounty:runtime-0001",
                external_reference="btys_runtime123",
            )

        result = self._run(executor)

        self.assertEqual("SUCCEEDED", result.execution.job.state)
        self.assertEqual("SUCCEEDED", result.execution.side_effect.state)
        self.assertIsNotNone(result.provenance)
        self.assertEqual("opp-whop-runtime-1", result.provenance.opportunity_id)
        self.assertEqual("bnty_runtime123", result.provenance.bounty_id)
        self.assertEqual(
            result.provenance,
            self.provenance.get_by_reference("btys_runtime123"),
        )

    def test_retryable_submission_never_creates_provenance(self):
        def executor(_reservation):
            self.effects.begin_attempt("whop-bounty:runtime-0001")
            return self.effects.mark_failed(
                "whop-bounty:runtime-0001",
                definitely_not_applied=True,
            )

        result = self._run(executor)

        self.assertEqual("FAILED_RETRYABLE", result.execution.job.state)
        self.assertIsNone(result.provenance)
        self.assertIsNone(self.provenance.get_by_reference("btys_missing123"))

    def test_ambiguous_submission_never_creates_provenance(self):
        def executor(_reservation):
            self.effects.begin_attempt("whop-bounty:runtime-0001")
            return self.effects.mark_failed(
                "whop-bounty:runtime-0001",
                definitely_not_applied=False,
            )

        result = self._run(executor)

        self.assertEqual("UNKNOWN", result.execution.job.state)
        self.assertIsNone(result.provenance)

    def test_confirmed_replay_is_idempotent_at_provenance_boundary(self):
        def executor(_reservation):
            self.effects.begin_attempt("whop-bounty:runtime-0001")
            return self.effects.mark_succeeded(
                "whop-bounty:runtime-0001",
                external_reference="btys_runtime456",
            )

        first = self._run(executor)
        self.assertIsNotNone(first.provenance)

        replayed = self.provenance.record_confirmed_submission(
            first.execution.binding,
            side_effect_ledger=self.effects,
        )
        self.assertEqual(first.provenance, replayed)


if __name__ == "__main__":
    unittest.main()
