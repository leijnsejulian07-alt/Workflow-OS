from __future__ import annotations

import unittest
from unittest import mock

from workflow_os.adapters.ffprobe_media_qc import MediaQCResult
from workflow_os.production_handoff import ProducerOutput
from workflow_os.qc_evidence import BoundMediaQC
from workflow_os.verified_production import verify_production_output


class VerifiedProductionTests(unittest.TestCase):
    def _source(self) -> ProducerOutput:
        return ProducerOutput(
            relative_path="outputs/final.mp4",
            media_type="video/mp4",
            size_bytes=1234,
            sha256="a" * 64,
            producer="captioned-clip-pipeline",
        )

    def _passed(self) -> MediaQCResult:
        return MediaQCResult(True, "technical media QC passed", 30_000, 1080, 1920, "h264", True)

    @mock.patch("workflow_os.verified_production.run_bound_media_qc")
    def test_promotes_exact_output_into_manifest(self, run_qc):
        source = self._source()
        run_qc.return_value = BoundMediaQC(source.sha256, source.size_bytes, self._passed())

        result = verify_production_output(
            "workspace",
            source,
            opportunity_id="opp-1",
            campaign_id="campaign-1",
            source_material_rights_verified=True,
            campaign_requirements_verified=True,
            disclosure_satisfied=True,
            expected_duration_ms=30_000,
        )

        self.assertEqual(result.source, source)
        self.assertEqual(result.qc.source_sha256, source.sha256)
        self.assertEqual(result.manifest.opportunity_id, "opp-1")
        self.assertEqual(result.manifest.campaign_id, "campaign-1")
        self.assertEqual(result.manifest.sha256, source.sha256)
        self.assertTrue(result.manifest.qc_passed)
        run_qc.assert_called_once_with("workspace", source, expected_duration_ms=30_000)

    @mock.patch("workflow_os.verified_production.run_bound_media_qc")
    def test_failed_qc_fails_closed(self, run_qc):
        source = self._source()
        failed = MediaQCResult(False, "duration mismatch", 10_000, 1080, 1920, "h264", True)
        run_qc.return_value = BoundMediaQC(source.sha256, source.size_bytes, failed)

        with self.assertRaisesRegex(ValueError, "technical QC did not pass"):
            verify_production_output(
                "workspace",
                source,
                opportunity_id="opp-1",
                campaign_id="campaign-1",
                source_material_rights_verified=True,
                campaign_requirements_verified=True,
                disclosure_satisfied=True,
            )

    @mock.patch("workflow_os.verified_production.run_bound_media_qc")
    def test_stale_qc_binding_fails_closed(self, run_qc):
        source = self._source()
        run_qc.return_value = BoundMediaQC("b" * 64, source.size_bytes, self._passed())

        with self.assertRaisesRegex(ValueError, "does not match"):
            verify_production_output(
                "workspace",
                source,
                opportunity_id="opp-1",
                campaign_id="campaign-1",
                source_material_rights_verified=True,
                campaign_requirements_verified=True,
                disclosure_satisfied=True,
            )

    @mock.patch("workflow_os.verified_production.run_bound_media_qc")
    def test_nontechnical_evidence_cannot_be_skipped(self, run_qc):
        source = self._source()
        run_qc.return_value = BoundMediaQC(source.sha256, source.size_bytes, self._passed())

        for kwargs in (
            {"source_material_rights_verified": False, "campaign_requirements_verified": True, "disclosure_satisfied": True},
            {"source_material_rights_verified": True, "campaign_requirements_verified": False, "disclosure_satisfied": True},
            {"source_material_rights_verified": True, "campaign_requirements_verified": True, "disclosure_satisfied": False},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    verify_production_output(
                        "workspace",
                        source,
                        opportunity_id="opp-1",
                        campaign_id="campaign-1",
                        **kwargs,
                    )

    def test_rejects_non_producer_output_before_qc(self):
        with self.assertRaisesRegex(ValueError, "source must be ProducerOutput"):
            verify_production_output(
                "workspace",
                object(),  # type: ignore[arg-type]
                opportunity_id="opp-1",
                campaign_id="campaign-1",
                source_material_rights_verified=True,
                campaign_requirements_verified=True,
                disclosure_satisfied=True,
            )


if __name__ == "__main__":
    unittest.main()
