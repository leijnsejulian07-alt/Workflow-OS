import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.durable_worker import VerifiedLeasedOpportunityJob
from workflow_os.job_queue import JobRecord
from workflow_os.openshorts_output_provenance import OpenShortsClipOutput
from workflow_os.openshorts_output_qc import OpenShortsOutputQCEvidence
from workflow_os.openshorts_whop_handoff import prepare_submit_reward_openshorts_whop_deliverable


class SubmitRewardQCBoundHandoffTests(unittest.TestCase):
    def setUp(self):
        self.key = "openshorts:7:" + "a" * 64
        self.output = OpenShortsClipOutput(
            idempotency_key=self.key,
            provider_job_id="provider-1",
            clip_index=0,
            video_url="https://cdn.example.com/watch/clip.mp4",
            download_url="https://cdn.example.com/download/clip.mp4",
            title="clip",
            evidence_sha256="d" * 64,
        )
        self.qc = OpenShortsOutputQCEvidence(
            idempotency_key=self.key,
            provider_job_id="provider-1",
            clip_index=0,
            provider_evidence_sha256="d" * 64,
            media_sha256="e" * 64,
            media_type="video/mp4",
            size_bytes=1234,
            duration_ms=15000,
            width=1080,
            height=1920,
            video_codec="h264",
            has_audio=True,
        )
        job = JobRecord(
            job_id=8,
            idempotency_key="submit:8",
            opportunity_id="opp-1",
            job_type="submit_reward",
            request_fingerprint="f" * 64,
            state="LEASED",
            attempt_count=1,
            max_attempts=3,
            available_at="2026-09-15T00:00:00+00:00",
            lease_expires_at="2026-09-15T00:05:00+00:00",
            worker_id="whop-worker",
            last_error=None,
        )
        payload = {
            "upstream_render": {
                "source_job_id": 7,
                "source_request_fingerprint": "c" * 64,
                "openshorts_idempotency_key": self.key,
                "provider_job_id": "provider-1",
                "clip_index": 0,
                "evidence_sha256": "d" * 64,
                "video_url": self.output.video_url,
            }
        }
        self.verified = VerifiedLeasedOpportunityJob(job=job, payload=payload, opportunity={})

    def _prepare(self, **kwargs):
        values = dict(
            verified_job=self.verified,
            output=self.output,
            technical_qc=self.qc,
            rights_verified=True,
            campaign_requirements_verified=True,
            disclosure_satisfied=True,
            caption=" campaign caption ",
        )
        values.update(kwargs)
        return prepare_submit_reward_openshorts_whop_deliverable(**values)

    def test_prepares_exact_qc_bound_child_deliverable(self):
        result = self._prepare()
        self.assertEqual(result.opportunity_id, "opp-1")
        self.assertEqual(result.openshorts_idempotency_key, self.key)
        self.assertEqual(result.deliverable.urls, (self.output.video_url,))
        self.assertEqual(result.deliverable.caption, "campaign caption")

    def test_rejects_naked_or_incomplete_nontechnical_authority(self):
        for field in ("rights_verified", "campaign_requirements_verified", "disclosure_satisfied"):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    self._prepare(**{field: False})

    def test_rejects_qc_identity_drift(self):
        bad = (
            replace(self.qc, idempotency_key="openshorts:9:" + "b" * 64),
            replace(self.qc, provider_job_id="other"),
            replace(self.qc, clip_index=1),
            replace(self.qc, provider_evidence_sha256="1" * 64),
        )
        for qc in bad:
            with self.subTest(qc=qc):
                with self.assertRaises(RuntimeError):
                    self._prepare(technical_qc=qc)

    def test_rejects_upstream_output_drift(self):
        payload = dict(self.verified.payload)
        upstream = dict(payload["upstream_render"])
        upstream["video_url"] = "https://cdn.example.com/watch/other.mp4"
        payload["upstream_render"] = upstream
        verified = replace(self.verified, payload=payload)
        with self.assertRaises(RuntimeError):
            self._prepare(verified_job=verified)

    def test_rejects_non_submit_reward_job(self):
        verified = replace(self.verified, job=replace(self.verified.job, job_type="produce_and_publish"))
        with self.assertRaises(RuntimeError):
            self._prepare(verified_job=verified)


if __name__ == "__main__":
    unittest.main()
