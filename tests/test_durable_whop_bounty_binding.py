import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from workflow_os.adapters.whop_bounty_execution import reserve_whop_bounty_submission
from workflow_os.adapters.whop_bounty_submission import (
    WhopBountyDeliverable,
    WhopBountySubmissionEvidence,
)
from workflow_os.durable_whop_bounty_binding import DurableWhopBountyBindingLedger
from workflow_os.durable_worker import VerifiedLeasedOpportunityJob
from workflow_os.job_queue import JobRecord
from workflow_os.side_effects import SideEffectLedger


class DurableWhopBountyBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.side_effects = SideEffectLedger(root / "side-effects.sqlite")
        self.bindings = DurableWhopBountyBindingLedger(root / "bindings.sqlite")
        self.evidence = WhopBountySubmissionEvidence(
            user_credential_verified=True,
            worker_identity_verified=True,
            rights_verified=True,
            campaign_requirements_verified=True,
            deliverable_verified=True,
        )
        self.deliverable = WhopBountyDeliverable(
            deliverable_type="content_url",
            urls=("https://example.com/work/123",),
            caption="verified deliverable",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _job(self, *, job_id=1, opportunity=None):
        opportunity = opportunity or {
            "opportunity_id": "opp-whop-1",
            "source_platform": "whop_bounties",
            "campaign_id": "bnty_example123",
            "bounty_type": "workforce",
            "machine_submission_verified": True,
        }
        record = JobRecord(
            job_id=job_id,
            idempotency_key=f"revenue:job-{job_id}",
            opportunity_id=opportunity["opportunity_id"],
            job_type="produce_and_publish",
            request_fingerprint=(f"{job_id:064x}"[-64:]),
            state="LEASED",
            attempt_count=1,
            max_attempts=3,
            available_at="2026-08-24T00:00:00+00:00",
            lease_expires_at="2026-08-24T00:05:00+00:00",
            worker_id="worker-1",
            last_error=None,
        )
        return VerifiedLeasedOpportunityJob(job=record, payload={}, opportunity=opportunity)

    def _reservation(self):
        return reserve_whop_bounty_submission(
            bounty_id="bnty_example123",
            deliverable=self.deliverable,
            evidence=self.evidence,
            idempotency_key="whop-bounty:job-0001",
            ledger=self.side_effects,
        )

    def test_binds_verified_workforce_job_to_exact_reserved_submission(self):
        binding = self.bindings.bind(
            self._job(),
            self._reservation(),
            side_effect_ledger=self.side_effects,
        )
        self.assertEqual(binding.opportunity_id, "opp-whop-1")
        self.assertEqual(binding.bounty_id, "bnty_example123")
        self.assertEqual(self.bindings.get(1), binding)

    def test_exact_replay_is_idempotent(self):
        job = self._job()
        reservation = self._reservation()
        first = self.bindings.bind(job, reservation, side_effect_ledger=self.side_effects)
        second = self.bindings.bind(job, reservation, side_effect_ledger=self.side_effects)
        self.assertEqual(first, second)

    def test_rejects_non_whop_opportunity(self):
        opportunity = dict(self._job().opportunity)
        opportunity["source_platform"] = "other"
        with self.assertRaisesRegex(RuntimeError, "not a Whop Bounties opportunity"):
            self.bindings.bind(
                self._job(opportunity=opportunity),
                self._reservation(),
                side_effect_ledger=self.side_effects,
            )

    def test_rejects_campaign_identity_drift(self):
        opportunity = dict(self._job().opportunity)
        opportunity["campaign_id"] = "bnty_other123"
        with self.assertRaisesRegex(RuntimeError, "does not match opportunity campaign"):
            self.bindings.bind(
                self._job(opportunity=opportunity),
                self._reservation(),
                side_effect_ledger=self.side_effects,
            )

    def test_rejects_non_workforce_bounty(self):
        opportunity = dict(self._job().opportunity)
        opportunity["bounty_type"] = "classic"
        opportunity["machine_submission_verified"] = False
        with self.assertRaisesRegex(RuntimeError, "only workforce bounties"):
            self.bindings.bind(
                self._job(opportunity=opportunity),
                self._reservation(),
                side_effect_ledger=self.side_effects,
            )

    def test_rejects_unverified_machine_submission(self):
        opportunity = dict(self._job().opportunity)
        opportunity["machine_submission_verified"] = False
        with self.assertRaisesRegex(RuntimeError, "machine submission is not verified"):
            self.bindings.bind(
                self._job(opportunity=opportunity),
                self._reservation(),
                side_effect_ledger=self.side_effects,
            )

    def test_rejects_binding_after_external_execution_has_started(self):
        reservation = self._reservation()
        self.side_effects.begin_attempt(reservation.idempotency_key)
        with self.assertRaisesRegex(RuntimeError, "not retry-authorized"):
            self.bindings.bind(
                self._job(),
                reservation,
                side_effect_ledger=self.side_effects,
            )

    def test_one_side_effect_cannot_bind_two_jobs(self):
        reservation = self._reservation()
        self.bindings.bind(self._job(job_id=1), reservation, side_effect_ledger=self.side_effects)
        with self.assertRaisesRegex(ValueError, "already bound to another durable job"):
            self.bindings.bind(
                self._job(job_id=2),
                reservation,
                side_effect_ledger=self.side_effects,
            )


if __name__ == "__main__":
    unittest.main()
