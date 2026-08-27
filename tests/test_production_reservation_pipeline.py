import tempfile
import unittest
from unittest.mock import patch

from workflow_os.adapters.ffprobe_media_qc import MediaQCResult
from workflow_os.production_assets import ProductionAssetManifest
from workflow_os.production_handoff import ProducerOutput
from workflow_os.production_reservation_pipeline import (
    _build_preflight_request,
    verify_and_reserve_production_submission,
)
from workflow_os.production_submission import ProductionSubmissionContext
from workflow_os.qc_evidence import BoundMediaQC
from workflow_os.side_effects import SideEffectLedger
from workflow_os.submissions import evaluate_submission
from workflow_os.verified_production import VerifiedProductionResult


DIGEST = "a" * 64


def source(**overrides):
    values = {
        "relative_path": "outputs/opp-1/final.mp4",
        "media_type": "video/mp4",
        "size_bytes": 1024,
        "sha256": DIGEST,
        "producer": "captioned-clip-v1",
    }
    values.update(overrides)
    return ProducerOutput(**values)


def context(**overrides):
    values = {
        "source_platform": "verified-machine-source",
        "campaign_url": "https://example.com/campaigns/example",
        "destination_url": "https://www.tiktok.com/upload",
        "caption": "Campaign-compliant caption",
        "account_authorized": True,
        "machine_submission_verified": True,
        "zero_touch_execution_enabled": True,
    }
    values.update(overrides)
    return ProductionSubmissionContext(**values)


def verified_result(src, **manifest_overrides):
    manifest_values = {
        "opportunity_id": "opp-1",
        "campaign_id": "campaign-1",
        "relative_path": src.relative_path,
        "media_type": src.media_type,
        "size_bytes": src.size_bytes,
        "sha256": src.sha256,
        "producer": src.producer,
        "source_material_rights_verified": True,
        "campaign_requirements_verified": True,
        "disclosure_satisfied": True,
        "qc_passed": True,
    }
    manifest_values.update(manifest_overrides)
    qc = BoundMediaQC(
        source_sha256=src.sha256,
        source_size_bytes=src.size_bytes,
        result=MediaQCResult(
            passed=True,
            reason="ok",
            duration_ms=15_000,
            width=1080,
            height=1920,
            video_codec="h264",
            has_audio=True,
        ),
    )
    return VerifiedProductionResult(
        source=src,
        qc=qc,
        manifest=ProductionAssetManifest(**manifest_values),
    )


class ProductionReservationPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.ledger = SideEffectLedger(f"{self.tempdir.name}/side-effects.sqlite3")
        self.src = source()
        self.ctx = context()
        self.kwargs = {
            "opportunity_id": "opp-1",
            "campaign_id": "campaign-1",
            "source_material_rights_verified": True,
            "campaign_requirements_verified": True,
            "disclosure_satisfied": True,
            "context": self.ctx,
            "allowed_destination_hosts": {"www.tiktok.com"},
            "ledger": self.ledger,
        }

    def tearDown(self):
        self.tempdir.cleanup()

    @patch("workflow_os.production_reservation_pipeline.verify_production_output")
    def test_verified_output_is_reserved(self, verify_mock):
        verify_mock.return_value = verified_result(self.src)
        prepared = verify_and_reserve_production_submission(self.tempdir.name, self.src, **self.kwargs)
        self.assertTrue(prepared.reservation.decision.allowed)
        self.assertEqual(prepared.reservation.side_effect.state, "RESERVED")
        verify_mock.assert_called_once()

    @patch("workflow_os.production_reservation_pipeline.verify_production_output")
    def test_unverified_machine_submission_fails_before_qc(self, verify_mock):
        blocked = context(
            source_platform="cliparmy",
            campaign_url="https://cliparmy.com/campaigns/example",
            machine_submission_verified=False,
            zero_touch_execution_enabled=False,
        )
        with self.assertRaisesRegex(ValueError, "machine submission authority is not verified"):
            verify_and_reserve_production_submission(
                self.tempdir.name, self.src, **{**self.kwargs, "context": blocked}
            )
        verify_mock.assert_not_called()

    @patch("workflow_os.production_reservation_pipeline.verify_production_output")
    def test_disabled_zero_touch_fails_before_qc(self, verify_mock):
        with self.assertRaisesRegex(ValueError, "zero-touch execution is not enabled"):
            verify_and_reserve_production_submission(
                self.tempdir.name,
                self.src,
                **{**self.kwargs, "context": context(zero_touch_execution_enabled=False)},
            )
        verify_mock.assert_not_called()

    @patch("workflow_os.production_reservation_pipeline.verify_production_output")
    def test_hostile_non_boolean_execution_authority_fails_before_qc(self, verify_mock):
        with self.assertRaisesRegex(ValueError, "machine_submission_verified must be boolean"):
            verify_and_reserve_production_submission(
                self.tempdir.name,
                self.src,
                **{**self.kwargs, "context": context(machine_submission_verified="true")},
            )
        verify_mock.assert_not_called()

    @patch("workflow_os.production_reservation_pipeline.verify_production_output")
    def test_unauthorized_account_fails_before_qc(self, verify_mock):
        with self.assertRaisesRegex(ValueError, "preflight rejected"):
            verify_and_reserve_production_submission(
                self.tempdir.name, self.src, **{**self.kwargs, "context": context(account_authorized=False)}
            )
        verify_mock.assert_not_called()

    @patch("workflow_os.production_reservation_pipeline.verify_production_output")
    def test_unknown_rights_fail_before_qc(self, verify_mock):
        with self.assertRaisesRegex(ValueError, "preflight rejected"):
            verify_and_reserve_production_submission(
                self.tempdir.name, self.src, **{**self.kwargs, "source_material_rights_verified": False}
            )
        verify_mock.assert_not_called()

    @patch("workflow_os.production_reservation_pipeline.verify_production_output")
    def test_identity_drift_after_qc_fails_before_ledger_mutation(self, verify_mock):
        verify_mock.return_value = verified_result(self.src, sha256="b" * 64)
        preflight_request = _build_preflight_request(
            self.src,
            opportunity_id="opp-1",
            context=self.ctx,
            source_material_rights_verified=True,
            campaign_requirements_verified=True,
            disclosure_satisfied=True,
        )
        preflight = evaluate_submission(preflight_request, allowed_destination_hosts={"www.tiktok.com"})
        with self.assertRaisesRegex(RuntimeError, "changed publication identity"):
            verify_and_reserve_production_submission(self.tempdir.name, self.src, **self.kwargs)
        self.assertIsNone(self.ledger.get(preflight.idempotency_key))

    @patch("workflow_os.production_reservation_pipeline.verify_production_output")
    def test_same_submission_reservation_is_idempotent(self, verify_mock):
        verify_mock.return_value = verified_result(self.src)
        first = verify_and_reserve_production_submission(self.tempdir.name, self.src, **self.kwargs)
        second = verify_and_reserve_production_submission(self.tempdir.name, self.src, **self.kwargs)
        self.assertEqual(first.reservation.side_effect.idempotency_key, second.reservation.side_effect.idempotency_key)
        self.assertEqual(second.reservation.side_effect.state, "RESERVED")


if __name__ == "__main__":
    unittest.main()
