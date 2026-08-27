from __future__ import annotations

from dataclasses import replace
import tempfile
import unittest
from pathlib import Path

from workflow_os.side_effects import SideEffectLedger
from workflow_os.website_fulfillment_gate import WebsiteScopeSnapshot
from workflow_os.website_handoff_execution import (
    WebsiteDeliveryProvenanceLedger,
    WebsiteHandoffAttemptResult,
    WebsiteHandoffReconciliationResult,
    execute_reserved_website_handoff,
    reconcile_unknown_website_handoff,
)
from workflow_os.website_handoff_reservation import WebsiteHandoffReservation
from workflow_os.website_static_build import BuiltStaticFile, WebsiteBuildArtifact


class WebsiteHandoffExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.side_effects = SideEffectLedger(root / "side-effects.sqlite")
        self.provenance = WebsiteDeliveryProvenanceLedger(root / "delivery.sqlite")
        digest = "a" * 64
        manifest = "b" * 64
        self.snapshot = WebsiteScopeSnapshot(
            opportunity_id="opp-website-1",
            lead_id="lead-1",
            pages=1,
            fixed_price_eur=350.0,
            quote_expires_at="2026-09-01T12:00:00+00:00",
            usage_rights="CUSTOMER_ATTESTED",
            customer_controls_domain=True,
            recurring_maintenance=False,
            mobile_responsive=True,
            basic_seo_metadata=True,
            contact_or_cta=True,
            payment_method="PAYMENT_LINK",
            approval_rules="FIXED_SCOPE",
            source_checked_at="2026-08-27T12:00:00+00:00",
            snapshot_sha256=digest,
        )
        built = BuiltStaticFile("index.html", "<html></html>", "c" * 64, 13)
        self.artifact = WebsiteBuildArtifact(
            opportunity_id=self.snapshot.opportunity_id,
            scope_sha256=digest,
            files=(built,),
            manifest_sha256=manifest,
            total_bytes=13,
        )
        record = self.side_effects.reserve(
            idempotency_key=f"website-handoff:{self.snapshot.opportunity_id}:{manifest}:CUSTOMER_DOWNLOAD",
            action="WEBSITE_HANDOFF",
            target="customer-download:lead-1",
            payload={
                "opportunity_id": self.snapshot.opportunity_id,
                "scope_sha256": digest,
                "manifest_sha256": manifest,
                "handoff_mode": "CUSTOMER_DOWNLOAD",
            },
            max_attempts=3,
        )
        self.reservation = WebsiteHandoffReservation(
            state="RESERVED_ONLY_NO_EXTERNAL_ACTION",
            reason="TEST",
            idempotency_key=record.idempotency_key,
            side_effect=record,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_confirmed_handoff_records_immutable_delivery_provenance(self) -> None:
        result = execute_reserved_website_handoff(
            self.reservation,
            ledger=self.side_effects,
            deliver=lambda: WebsiteHandoffAttemptResult("APPLIED", "delivery-123"),
        )
        self.assertEqual(result.state, "SUCCEEDED")
        provenance = self.provenance.record_confirmed_delivery(
            self.snapshot,
            self.artifact,
            self.reservation,
            side_effect_ledger=self.side_effects,
        )
        self.assertEqual(provenance.opportunity_id, self.snapshot.opportunity_id)
        self.assertEqual(provenance.manifest_sha256, self.artifact.manifest_sha256)
        self.assertEqual(provenance.delivery_reference, "delivery-123")
        replay = self.provenance.record_confirmed_delivery(
            self.snapshot,
            self.artifact,
            self.reservation,
            side_effect_ledger=self.side_effects,
        )
        self.assertEqual(replay, provenance)

    def test_ambiguous_handoff_becomes_unknown_and_cannot_create_provenance(self) -> None:
        result = execute_reserved_website_handoff(
            self.reservation,
            ledger=self.side_effects,
            deliver=lambda: WebsiteHandoffAttemptResult("UNKNOWN"),
        )
        self.assertEqual(result.state, "UNKNOWN")
        with self.assertRaisesRegex(RuntimeError, "confirmed SUCCEEDED"):
            self.provenance.record_confirmed_delivery(
                self.snapshot,
                self.artifact,
                self.reservation,
                side_effect_ledger=self.side_effects,
            )
        with self.assertRaisesRegex(RuntimeError, "not execution-authorized"):
            execute_reserved_website_handoff(
                self.reservation,
                ledger=self.side_effects,
                deliver=lambda: WebsiteHandoffAttemptResult("APPLIED", "duplicate-risk"),
            )

    def test_unknown_handoff_reconciles_to_success_without_redispatch(self) -> None:
        execute_reserved_website_handoff(
            self.reservation,
            ledger=self.side_effects,
            deliver=lambda: WebsiteHandoffAttemptResult("UNKNOWN"),
        )
        result = reconcile_unknown_website_handoff(
            ledger=self.side_effects,
            idempotency_key=self.reservation.idempotency_key,
            reconcile=lambda: WebsiteHandoffReconciliationResult("FOUND_APPLIED", "delivery-after-probe"),
        )
        self.assertEqual(result.state, "SUCCEEDED")
        self.assertEqual(result.external_reference, "delivery-after-probe")

    def test_provenance_rejects_artifact_identity_drift(self) -> None:
        execute_reserved_website_handoff(
            self.reservation,
            ledger=self.side_effects,
            deliver=lambda: WebsiteHandoffAttemptResult("APPLIED", "delivery-456"),
        )
        drifted = replace(self.artifact, scope_sha256="d" * 64)
        with self.assertRaisesRegex(ValueError, "artifact identity mismatch"):
            self.provenance.record_confirmed_delivery(
                self.snapshot,
                drifted,
                self.reservation,
                side_effect_ledger=self.side_effects,
            )

    def test_not_applied_is_retryable_only_when_proven(self) -> None:
        result = execute_reserved_website_handoff(
            self.reservation,
            ledger=self.side_effects,
            deliver=lambda: WebsiteHandoffAttemptResult("NOT_APPLIED"),
        )
        self.assertEqual(result.state, "FAILED_RETRYABLE")
        retry = execute_reserved_website_handoff(
            self.reservation,
            ledger=self.side_effects,
            deliver=lambda: WebsiteHandoffAttemptResult("APPLIED", "delivery-retry"),
        )
        self.assertEqual(retry.state, "SUCCEEDED")
        self.assertEqual(retry.attempt_count, 2)


if __name__ == "__main__":
    unittest.main()
