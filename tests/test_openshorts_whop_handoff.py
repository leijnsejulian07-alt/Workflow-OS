import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.openshorts_job_preparation import PreparedOpenShortsProcessing
from workflow_os.openshorts_output_provenance import OpenShortsClipOutput
from workflow_os.openshorts_whop_handoff import (
    OpenShortsWhopHandoffEvidence,
    prepare_openshorts_whop_deliverable,
)
from workflow_os.side_effects import SideEffectRecord


class OpenShortsWhopHandoffTests(unittest.TestCase):
    def setUp(self):
        self.key = "openshorts:7:" + "a" * 64
        self.job_id = "job_123"
        reservation = SideEffectRecord(
            idempotency_key=self.key,
            action="openshorts.process",
            target="https://api.openshorts.app/api/process",
            request_fingerprint="b" * 64,
            state="SUCCEEDED",
            attempt_count=1,
            max_attempts=2,
            external_reference=self.job_id,
        )
        self.processing = PreparedOpenShortsProcessing(
            reservation=reservation,
            opportunity_id="opp-1",
            job_id=7,
            job_request_fingerprint="c" * 64,
            source_url="https://youtube.com/watch?v=abc",
            webhook_url="https://example.com/hooks/openshorts",
            captions=True,
            auto_hook=True,
        )
        self.output = OpenShortsClipOutput(
            idempotency_key=self.key,
            provider_job_id=self.job_id,
            clip_index=0,
            video_url="https://cdn.example.com/watch/clip-0.mp4",
            download_url="https://cdn.example.com/download/clip-0.mp4",
            title="Best moment",
            evidence_sha256="d" * 64,
        )
        self.evidence = OpenShortsWhopHandoffEvidence(True, True, True, True)

    def test_prepares_content_url_deliverable(self):
        result = prepare_openshorts_whop_deliverable(
            processing=self.processing,
            output=self.output,
            evidence=self.evidence,
            caption="  campaign caption  ",
        )
        self.assertEqual(result.opportunity_id, "opp-1")
        self.assertEqual(result.provider_job_id, self.job_id)
        self.assertEqual(result.evidence_sha256, "d" * 64)
        self.assertEqual(result.deliverable.deliverable_type, "content_url")
        self.assertEqual(result.deliverable.urls, (self.output.video_url,))
        self.assertEqual(result.deliverable.caption, "campaign caption")

    def test_requires_all_handoff_evidence(self):
        fields = ("rights_verified", "campaign_requirements_verified", "disclosure_satisfied", "qc_passed")
        for field in fields:
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    prepare_openshorts_whop_deliverable(
                        processing=self.processing,
                        output=self.output,
                        evidence=replace(self.evidence, **{field: False}),
                    )

    def test_rejects_reservation_and_provider_identity_drift(self):
        bad_outputs = (
            replace(self.output, idempotency_key="openshorts:8:" + "e" * 64),
            replace(self.output, provider_job_id="job_other"),
        )
        for output in bad_outputs:
            with self.subTest(output=output):
                with self.assertRaises(RuntimeError):
                    prepare_openshorts_whop_deliverable(
                        processing=self.processing, output=output, evidence=self.evidence
                    )

    def test_requires_succeeded_openshorts_reservation(self):
        processing = replace(
            self.processing,
            reservation=replace(self.processing.reservation, state="UNKNOWN"),
        )
        with self.assertRaises(RuntimeError):
            prepare_openshorts_whop_deliverable(
                processing=processing, output=self.output, evidence=self.evidence
            )

    def test_rejects_wrong_side_effect_action(self):
        processing = replace(
            self.processing,
            reservation=replace(self.processing.reservation, action="other.action"),
        )
        with self.assertRaises(RuntimeError):
            prepare_openshorts_whop_deliverable(
                processing=processing, output=self.output, evidence=self.evidence
            )

    def test_caption_is_bounded_and_control_character_safe(self):
        for caption in ("x" * 4001, "bad\x00caption"):
            with self.subTest(caption=caption[:20]):
                with self.assertRaises(ValueError):
                    prepare_openshorts_whop_deliverable(
                        processing=self.processing,
                        output=self.output,
                        evidence=self.evidence,
                        caption=caption,
                    )


if __name__ == "__main__":
    unittest.main()
