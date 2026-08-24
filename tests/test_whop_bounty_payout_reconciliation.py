from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from workflow_os.audit import AuditRevenueLedger
from workflow_os.reconciliation import ReconciledEvent, RevenueReconciliationLedger
from workflow_os.reconciliation_attribution import AttributedCashReceipt
from workflow_os.whop_bounty_payout_attribution import WhopBountyPayoutEvidence
from workflow_os.whop_bounty_payout_reconciliation import (
    reconcile_whop_bounty_payout_to_scaling_truth,
)
from workflow_os.whop_bounty_submission_provenance import (
    WhopBountySubmissionProvenance,
    WhopBountySubmissionProvenanceLedger,
)


class WhopBountyPayoutReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.audit = AuditRevenueLedger(root / "audit.sqlite")
        self.provenance = WhopBountySubmissionProvenanceLedger(root / "provenance.sqlite")
        self.reconciliation = RevenueReconciliationLedger(root / "reconciliation.sqlite")
        self.evidence = WhopBountyPayoutEvidence(
            payout_event_id="payout-whop-1",
            receipt_id="receipt-whop-1",
            submission_reference="btys_submission123",
            evidence_sha256="a" * 64,
        )
        self.provenance_record = WhopBountySubmissionProvenance(
            opportunity_id="opp-whop-1",
            bounty_id="bnty_example123",
            side_effect_idempotency_key="side-whop-1",
            side_effect_request_fingerprint="b" * 64,
            submission_target="https://api.whop.com/api/v1/bounty_submissions",
            submission_reference="btys_submission123",
        )
        self.attributed = AttributedCashReceipt(
            receipt_id="receipt-whop-1",
            source_platform="whop_bounties",
            opportunity_id="opp-whop-1",
            amount_eur="40.00",
            received_at="2026-08-24T12:00:00+00:00",
            external_reference="payout-whop-1",
        )
        self.reconciled = ReconciledEvent(
            platform="whop_bounties",
            external_event_id="audit-receipt:receipt-whop-1",
            opportunity_id="opp-whop-1",
            event_type="CASH_RECEIVED",
            amount_cents=4000,
            occurred_at="2026-08-24T12:00:00+00:00",
            evidence_sha256="c" * 64,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @mock.patch(
        "workflow_os.whop_bounty_payout_reconciliation.promote_attributed_cash_receipt"
    )
    @mock.patch(
        "workflow_os.whop_bounty_payout_reconciliation.load_attributed_cash_receipt"
    )
    @mock.patch(
        "workflow_os.whop_bounty_payout_reconciliation.attribute_cash_from_whop_bounty_evidence"
    )
    def test_handoff_uses_proven_identity_and_separate_settlement_evidence(
        self, attribute, load, promote
    ) -> None:
        attribute.return_value = self.provenance_record
        load.return_value = self.attributed
        promote.return_value = self.reconciled

        result = reconcile_whop_bounty_payout_to_scaling_truth(
            audit_ledger=self.audit,
            provenance_ledger=self.provenance,
            reconciliation_ledger=self.reconciliation,
            evidence=self.evidence,
            settlement_evidence_sha256="c" * 64,
        )

        self.assertEqual(self.provenance_record, result.provenance)
        self.assertEqual(self.reconciled, result.reconciled_event)
        attribute.assert_called_once_with(
            audit_ledger=self.audit,
            provenance_ledger=self.provenance,
            evidence=self.evidence,
        )
        load.assert_called_once_with(self.audit.path, "receipt-whop-1")
        promote.assert_called_once_with(
            legacy_db_path=self.audit.path,
            reconciliation_ledger=self.reconciliation,
            receipt_id="receipt-whop-1",
            evidence_sha256="c" * 64,
        )

    @mock.patch(
        "workflow_os.whop_bounty_payout_reconciliation.promote_attributed_cash_receipt"
    )
    @mock.patch(
        "workflow_os.whop_bounty_payout_reconciliation.load_attributed_cash_receipt"
    )
    @mock.patch(
        "workflow_os.whop_bounty_payout_reconciliation.attribute_cash_from_whop_bounty_evidence"
    )
    def test_attribution_identity_drift_stops_before_scaling_truth(
        self, attribute, load, promote
    ) -> None:
        attribute.return_value = self.provenance_record
        load.return_value = AttributedCashReceipt(
            receipt_id="receipt-whop-1",
            source_platform="whop_bounties",
            opportunity_id="opp-other",
            amount_eur="40.00",
            received_at="2026-08-24T12:00:00+00:00",
            external_reference="payout-whop-1",
        )

        with self.assertRaisesRegex(RuntimeError, "does not match Whop bounty"):
            reconcile_whop_bounty_payout_to_scaling_truth(
                audit_ledger=self.audit,
                provenance_ledger=self.provenance,
                reconciliation_ledger=self.reconciliation,
                evidence=self.evidence,
                settlement_evidence_sha256="c" * 64,
            )
        promote.assert_not_called()

    @mock.patch(
        "workflow_os.whop_bounty_payout_reconciliation.promote_attributed_cash_receipt"
    )
    @mock.patch(
        "workflow_os.whop_bounty_payout_reconciliation.load_attributed_cash_receipt"
    )
    @mock.patch(
        "workflow_os.whop_bounty_payout_reconciliation.attribute_cash_from_whop_bounty_evidence"
    )
    def test_reconciled_identity_must_still_match(self, attribute, load, promote) -> None:
        attribute.return_value = self.provenance_record
        load.return_value = self.attributed
        promote.return_value = ReconciledEvent(
            platform="whop_bounties",
            external_event_id="audit-receipt:receipt-whop-1",
            opportunity_id="opp-other",
            event_type="CASH_RECEIVED",
            amount_cents=4000,
            occurred_at="2026-08-24T12:00:00+00:00",
            evidence_sha256="c" * 64,
        )

        with self.assertRaisesRegex(RuntimeError, "does not match Whop bounty"):
            reconcile_whop_bounty_payout_to_scaling_truth(
                audit_ledger=self.audit,
                provenance_ledger=self.provenance,
                reconciliation_ledger=self.reconciliation,
                evidence=self.evidence,
                settlement_evidence_sha256="c" * 64,
            )

    def test_wrong_ledger_types_fail_before_any_work(self) -> None:
        with self.assertRaises(TypeError):
            reconcile_whop_bounty_payout_to_scaling_truth(
                audit_ledger=object(),
                provenance_ledger=self.provenance,
                reconciliation_ledger=self.reconciliation,
                evidence=self.evidence,
                settlement_evidence_sha256="c" * 64,
            )


if __name__ == "__main__":
    unittest.main()
