from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from workflow_os.adapters.whop_bounty_submission import WhopBountyDeliverable
from workflow_os.durable_worker import VerifiedLeasedOpportunityJob
from workflow_os.job_queue import JobRecord
from workflow_os.openshorts_whop_handoff import PreparedOpenShortsWhopDeliverable
from workflow_os.openshorts_whop_reservation import reserve_verified_openshorts_whop_submission
from workflow_os.side_effects import SideEffectLedger


class OpenShortsWhopReservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = SideEffectLedger(Path(self.tmp.name) / "effects.sqlite")

    def tearDown(self):
        self.tmp.cleanup()

    def _job(self):
        opportunity = {
            "opportunity_id": "opp-whop-1",
            "source_platform": "whop_bounties",
            "campaign_id": "bnty_example123",
            "bounty_type": "workforce",
            "machine_submission_verified": True,
            "zero_touch_execution_enabled": True,
            "rights_verification_state": "VERIFIED",
            "account_authorized": True,
            "worker_identity_verified": True,
            "campaign_requirements_verified": True,
            "deliverable_requirements_verified": True,
        }
        record = JobRecord(
            job_id=7,
            idempotency_key="revenue:example:1",
            opportunity_id="opp-whop-1",
            job_type="produce_and_publish",
            request_fingerprint="a" * 64,
            state="LEASED",
            attempt_count=1,
            max_attempts=3,
            available_at="2026-09-13T20:00:00+00:00",
            lease_expires_at="2026-09-13T20:05:00+00:00",
            worker_id="worker-1",
            last_error=None,
        )
        return VerifiedLeasedOpportunityJob(job=record, payload={}, opportunity=opportunity)

    def _handoff(self):
        return PreparedOpenShortsWhopDeliverable(
            opportunity_id="opp-whop-1",
            openshorts_idempotency_key="openshorts:7:" + "b" * 64,
            provider_job_id="job_123",
            clip_index=0,
            evidence_sha256="c" * 64,
            deliverable=WhopBountyDeliverable(
                deliverable_type="content_url",
                urls=("https://cdn.example.com/clip.mp4",),
                caption="campaign caption",
            ),
        )

    def test_reserves_exact_verified_handoff(self):
        result = reserve_verified_openshorts_whop_submission(
            self._job(),
            self._handoff(),
            credential_authority_verified=True,
            ledger=self.ledger,
        )
        self.assertEqual(result.submission.opportunity_id, "opp-whop-1")
        self.assertEqual(result.submission.job_id, 7)
        self.assertEqual(result.openshorts_provider_job_id, "job_123")
        self.assertEqual(result.submission.reservation.side_effect.state, "RESERVED")

    def test_rejects_opportunity_identity_drift(self):
        with self.assertRaises(RuntimeError):
            reserve_verified_openshorts_whop_submission(
                self._job(),
                replace(self._handoff(), opportunity_id="opp-other"),
                credential_authority_verified=True,
                ledger=self.ledger,
            )

    def test_rejects_durable_job_identity_drift(self):
        with self.assertRaises(RuntimeError):
            reserve_verified_openshorts_whop_submission(
                self._job(),
                replace(self._handoff(), openshorts_idempotency_key="openshorts:8:" + "d" * 64),
                credential_authority_verified=True,
                ledger=self.ledger,
            )

    def test_credential_authority_remains_separate(self):
        with self.assertRaises(ValueError):
            reserve_verified_openshorts_whop_submission(
                self._job(), self._handoff(), credential_authority_verified=False, ledger=self.ledger
            )

    def test_replay_is_idempotent_but_deliverable_drift_conflicts(self):
        first = reserve_verified_openshorts_whop_submission(
            self._job(), self._handoff(), credential_authority_verified=True, ledger=self.ledger
        )
        second = reserve_verified_openshorts_whop_submission(
            self._job(), self._handoff(), credential_authority_verified=True, ledger=self.ledger
        )
        self.assertEqual(
            first.submission.reservation.side_effect.request_fingerprint,
            second.submission.reservation.side_effect.request_fingerprint,
        )
        changed = replace(
            self._handoff(),
            deliverable=WhopBountyDeliverable(
                deliverable_type="content_url",
                urls=("https://cdn.example.com/other.mp4",),
            ),
        )
        with self.assertRaises(ValueError):
            reserve_verified_openshorts_whop_submission(
                self._job(), changed, credential_authority_verified=True, ledger=self.ledger
            )


if __name__ == "__main__":
    unittest.main()
