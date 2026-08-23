from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from workflow_os.audit import AuditRevenueLedger
from workflow_os.publication_payout_attribution import PublicationPayoutEvidence
from workflow_os.publication_provenance import PublicationProvenance, PublicationProvenanceLedger
from workflow_os.payout_reconciliation_pipeline import reconcile_publication_payout_to_scaling_truth
from workflow_os.reconciliation import ReconciledEvent, RevenueReconciliationLedger
from workflow_os.reconciliation_attribution import AttributedCashReceipt


class PayoutReconciliationPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.audit = AuditRevenueLedger(root / "audit.sqlite")
        self.provenance = PublicationProvenanceLedger(root / "provenance.sqlite")
        self.reconciliation = RevenueReconciliationLedger(root / "reconciliation.sqlite")
        self.evidence = PublicationPayoutEvidence(
            payout_event_id="payout-1",
            receipt_id="receipt-1",
            publication_target="tiktok",
            publication_reference="post-1",
            evidence_sha256="a" * 64,
        )
        self.provenance_record = PublicationProvenance(
            opportunity_id="opp-1",
            side_effect_idempotency_key="side-1",
            side_effect_request_fingerprint="b" * 64,
            publication_target="tiktok",
            publication_reference="post-1",
        )
        self.attributed = AttributedCashReceipt(
            receipt_id="receipt-1",
            source_platform="campaign-platform",
            opportunity_id="opp-1",
            amount_eur="12.34",
            received_at="2026-08-23T04:00:00+00:00",
            external_reference="payout-1",
        )
        self.reconciled = ReconciledEvent(
            platform="campaign-platform",
            external_event_id="audit-receipt:receipt-1",
            opportunity_id="opp-1",
            event_type="CASH_RECEIVED",
            amount_cents=1234,
            occurred_at="2026-08-23T04:00:00+00:00",
            evidence_sha256="c" * 64,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @mock.patch("workflow_os.payout_reconciliation_pipeline.promote_attributed_cash_receipt")
    @mock.patch("workflow_os.payout_reconciliation_pipeline.load_attributed_cash_receipt")
    @mock.patch("workflow_os.payout_reconciliation_pipeline.attribute_cash_from_publication_evidence")
    def test_handoff_uses_proven_identity_and_separate_settlement_evidence(
        self, attribute, load, promote
    ) -> None:
        attribute.return_value = self.provenance_record
        load.return_value = self.attributed
        promote.return_value = self.reconciled

        result = reconcile_publication_payout_to_scaling_truth(
            audit_ledger=self.audit,
            provenance_ledger=self.provenance,
            reconciliation_ledger=self.reconciliation,
            evidence=self.evidence,
            settlement_evidence_sha256="c" * 64,
        )

        self.assertEqual(result.provenance, self.provenance_record)
        self.assertEqual(result.reconciled_event, self.reconciled)
        attribute.assert_called_once_with(
            audit_ledger=self.audit,
            provenance_ledger=self.provenance,
            evidence=self.evidence,
        )
        load.assert_called_once_with(self.audit.path, "receipt-1")
        promote.assert_called_once_with(
            legacy_db_path=self.audit.path,
            reconciliation_ledger=self.reconciliation,
            receipt_id="receipt-1",
            evidence_sha256="c" * 64,
        )

    @mock.patch("workflow_os.payout_reconciliation_pipeline.promote_attributed_cash_receipt")
    @mock.patch("workflow_os.payout_reconciliation_pipeline.load_attributed_cash_receipt")
    @mock.patch("workflow_os.payout_reconciliation_pipeline.attribute_cash_from_publication_evidence")
    def test_identity_drift_stops_before_scaling_truth(self, attribute, load, promote) -> None:
        attribute.return_value = self.provenance_record
        load.return_value = AttributedCashReceipt(
            receipt_id="receipt-1",
            source_platform="campaign-platform",
            opportunity_id="opp-other",
            amount_eur="12.34",
            received_at="2026-08-23T04:00:00+00:00",
            external_reference="payout-1",
        )

        with self.assertRaisesRegex(RuntimeError, "does not match publication provenance"):
            reconcile_publication_payout_to_scaling_truth(
                audit_ledger=self.audit,
                provenance_ledger=self.provenance,
                reconciliation_ledger=self.reconciliation,
                evidence=self.evidence,
                settlement_evidence_sha256="c" * 64,
            )

        promote.assert_not_called()

    @mock.patch("workflow_os.payout_reconciliation_pipeline.promote_attributed_cash_receipt")
    @mock.patch("workflow_os.payout_reconciliation_pipeline.load_attributed_cash_receipt")
    @mock.patch("workflow_os.payout_reconciliation_pipeline.attribute_cash_from_publication_evidence")
    def test_reconciled_identity_must_still_match(self, attribute, load, promote) -> None:
        attribute.return_value = self.provenance_record
        load.return_value = self.attributed
        promote.return_value = ReconciledEvent(
            platform="campaign-platform",
            external_event_id="audit-receipt:receipt-1",
            opportunity_id="opp-other",
            event_type="CASH_RECEIVED",
            amount_cents=1234,
            occurred_at="2026-08-23T04:00:00+00:00",
            evidence_sha256="c" * 64,
        )

        with self.assertRaisesRegex(RuntimeError, "does not match publication provenance"):
            reconcile_publication_payout_to_scaling_truth(
                audit_ledger=self.audit,
                provenance_ledger=self.provenance,
                reconciliation_ledger=self.reconciliation,
                evidence=self.evidence,
                settlement_evidence_sha256="c" * 64,
            )

    def test_wrong_ledger_types_fail_before_any_work(self) -> None:
        with self.assertRaises(TypeError):
            reconcile_publication_payout_to_scaling_truth(
                audit_ledger=object(),
                provenance_ledger=self.provenance,
                reconciliation_ledger=self.reconciliation,
                evidence=self.evidence,
                settlement_evidence_sha256="c" * 64,
            )


if __name__ == "__main__":
    unittest.main()
