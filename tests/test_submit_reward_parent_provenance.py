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


class SubmitRewardParentProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = SideEffectLedger(Path(self.tmp.name) / "effects.sqlite")

    def tearDown(self):
        self.tmp.cleanup()

    def _opportunity(self):
        return {
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

    def _job(self):
        record = JobRecord(
            job_id=88,
            idempotency_key="whop-submit:41:" + "a" * 64,
            opportunity_id="opp-whop-1",
            job_type="submit_reward",
            request_fingerprint="d" * 64,
            state="LEASED",
            attempt_count=1,
            max_attempts=3,
            available_at="2026-09-14T20:00:00+00:00",
            lease_expires_at="2026-09-14T20:05:00+00:00",
            worker_id="whop-worker-1",
            last_error=None,
        )
        payload = {
            "upstream_render": {
                "source_job_id": 41,
                "source_request_fingerprint": "e" * 64,
                "openshorts_idempotency_key": "openshorts:41:" + "b" * 64,
                "provider_job_id": "job_123",
                "clip_index": 2,
                "evidence_sha256": "c" * 64,
                "video_url": "https://cdn.example.com/clip.mp4",
                "download_url": "https://cdn.example.com/clip.mp4",
                "title": "clip",
            }
        }
        return VerifiedLeasedOpportunityJob(job=record, payload=payload, opportunity=self._opportunity())

    def _handoff(self):
        return PreparedOpenShortsWhopDeliverable(
            opportunity_id="opp-whop-1",
            openshorts_idempotency_key="openshorts:41:" + "b" * 64,
            provider_job_id="job_123",
            clip_index=2,
            evidence_sha256="c" * 64,
            deliverable=WhopBountyDeliverable(
                deliverable_type="content_url",
                urls=("https://cdn.example.com/clip.mp4",),
                caption="campaign caption",
            ),
        )

    def test_submit_reward_reserves_against_parent_render_provenance(self):
        result = reserve_verified_openshorts_whop_submission(
            self._job(),
            self._handoff(),
            credential_authority_verified=True,
            ledger=self.ledger,
        )
        self.assertEqual(result.submission.job_id, 88)
        self.assertEqual(result.openshorts_provider_job_id, "job_123")
        self.assertEqual(result.submission.reservation.side_effect.state, "RESERVED")

    def test_rejects_child_job_id_as_fake_render_parent(self):
        with self.assertRaises(RuntimeError):
            reserve_verified_openshorts_whop_submission(
                self._job(),
                replace(self._handoff(), openshorts_idempotency_key="openshorts:88:" + "b" * 64),
                credential_authority_verified=True,
                ledger=self.ledger,
            )

    def test_rejects_provider_or_output_drift(self):
        with self.assertRaises(RuntimeError):
            reserve_verified_openshorts_whop_submission(
                self._job(),
                replace(self._handoff(), provider_job_id="job_other"),
                credential_authority_verified=True,
                ledger=self.ledger,
            )
        changed = replace(
            self._handoff(),
            deliverable=WhopBountyDeliverable(
                deliverable_type="content_url",
                urls=("https://cdn.example.com/other.mp4",),
            ),
        )
        with self.assertRaises(RuntimeError):
            reserve_verified_openshorts_whop_submission(
                self._job(), changed, credential_authority_verified=True, ledger=self.ledger
            )


if __name__ == "__main__":
    unittest.main()
