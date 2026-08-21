from __future__ import annotations

import unittest
from unittest import mock

from workflow_os.adapters.ffprobe_media_qc import MediaQCResult
from workflow_os.production_handoff import ProducerOutput
from workflow_os.qc_evidence import BoundMediaQC, build_trusted_production_evidence, run_bound_media_qc


class QCEvidenceTests(unittest.TestCase):
    def _source(self, *, digest: str = "a" * 64, size: int = 1234) -> ProducerOutput:
        return ProducerOutput(
            relative_path="outputs/final.mp4",
            media_type="video/mp4",
            size_bytes=size,
            sha256=digest,
            producer="captioned-clip-pipeline",
        )

    def _passed(self) -> MediaQCResult:
        return MediaQCResult(True, "technical media QC passed", 30_000, 1080, 1920, "h264", True)

    @mock.patch("workflow_os.qc_evidence.probe_media_qc")
    def test_run_binds_qc_to_exact_source_evidence(self, probe):
        source = self._source()
        probe.return_value = self._passed()

        bound = run_bound_media_qc("workspace", source, expected_duration_ms=30_000)

        self.assertEqual(bound.source_sha256, source.sha256)
        self.assertEqual(bound.source_size_bytes, source.size_bytes)
        self.assertTrue(bound.result.passed)
        probe.assert_called_once_with("workspace", source, expected_duration_ms=30_000)

    def test_builds_trusted_evidence_only_after_independent_gates(self):
        source = self._source()
        qc = BoundMediaQC(source.sha256, source.size_bytes, self._passed())

        evidence = build_trusted_production_evidence(
            source,
            qc,
            opportunity_id="opp-1",
            campaign_id="campaign-1",
            source_material_rights_verified=True,
            campaign_requirements_verified=True,
            disclosure_satisfied=True,
        )

        self.assertTrue(evidence.qc_passed)
        self.assertTrue(evidence.source_material_rights_verified)
        self.assertTrue(evidence.campaign_requirements_verified)
        self.assertTrue(evidence.disclosure_satisfied)

    def test_stale_qc_digest_fails_closed(self):
        source = self._source()
        stale = BoundMediaQC("b" * 64, source.size_bytes, self._passed())

        with self.assertRaisesRegex(ValueError, "does not match"):
            build_trusted_production_evidence(
                source,
                stale,
                opportunity_id="opp-1",
                campaign_id="campaign-1",
                source_material_rights_verified=True,
                campaign_requirements_verified=True,
                disclosure_satisfied=True,
            )

    def test_stale_qc_size_fails_closed(self):
        source = self._source()
        stale = BoundMediaQC(source.sha256, source.size_bytes + 1, self._passed())

        with self.assertRaisesRegex(ValueError, "does not match"):
            build_trusted_production_evidence(
                source,
                stale,
                opportunity_id="opp-1",
                campaign_id="campaign-1",
                source_material_rights_verified=True,
                campaign_requirements_verified=True,
                disclosure_satisfied=True,
            )

    def test_failed_qc_cannot_be_promoted(self):
        source = self._source()
        failed = MediaQCResult(False, "audio stream is required", 30_000, 1080, 1920, "h264", False)
        qc = BoundMediaQC(source.sha256, source.size_bytes, failed)

        with self.assertRaisesRegex(ValueError, "technical QC did not pass"):
            build_trusted_production_evidence(
                source,
                qc,
                opportunity_id="opp-1",
                campaign_id="campaign-1",
                source_material_rights_verified=True,
                campaign_requirements_verified=True,
                disclosure_satisfied=True,
            )

    def test_technical_qc_cannot_self_grant_nontechnical_evidence(self):
        source = self._source()
        qc = BoundMediaQC(source.sha256, source.size_bytes, self._passed())

        for kwargs, expected in (
            ({"source_material_rights_verified": False, "campaign_requirements_verified": True, "disclosure_satisfied": True}, "rights"),
            ({"source_material_rights_verified": True, "campaign_requirements_verified": False, "disclosure_satisfied": True}, "campaign"),
            ({"source_material_rights_verified": True, "campaign_requirements_verified": True, "disclosure_satisfied": False}, "disclosure"),
        ):
            with self.subTest(expected=expected):
                with self.assertRaises(ValueError):
                    build_trusted_production_evidence(
                        source,
                        qc,
                        opportunity_id="opp-1",
                        campaign_id="campaign-1",
                        **kwargs,
                    )


if __name__ == "__main__":
    unittest.main()
