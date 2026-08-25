from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from workflow_os.audit import AuditRevenueLedger
from workflow_os.reconciliation import ReconciledEvent, RevenueReconciliationLedger
from workflow_os.scaling_control import ScalingDirective
from workflow_os.whop_bounty_payout_attribution import WhopBountyPayoutEvidence
from workflow_os.whop_bounty_payout_reconciliation import WhopBountyPayoutReconciliationResult
from workflow_os.whop_bounty_settlement_feedback import (
    reconcile_whop_bounty_payout_and_decide_next_action,
)
from workflow_os.whop_bounty_submission_provenance import (
    WhopBountySubmissionProvenance,
    WhopBountySubmissionProvenanceLedger,
)


class WhopBountySettlementFeedbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.audit = AuditRevenueLedger(root / "audit.sqlite")
        self.provenance = WhopBountySubmissionProvenanceLedger(root / "provenance.sqlite")
        self.reconciliation = RevenueReconciliationLedger(root / "reconciliation.sqlite")
        self.evidence = WhopBountyPayoutEvidence(
            payout_event_id="payout-1",
            receipt_id="receipt-1",
            submission_reference="btys_submission123",
            evidence_sha256="a" * 64,
        )
        self.provenance_record = WhopBountySubmissionProvenance(
            opportunity_id="opp-1",
            bounty_id="bnty_example123",
            side_effect_idempotency_key="side-1",
            side_effect_request_fingerprint="b" * 64,
            submission_target="https://api.whop.com/api/v1/bounty_submissions",
            submission_reference="btys_submission123",
        )
        self.reconciled = ReconciledEvent(
            platform="whop_bounties",
            external_event_id="audit-receipt:receipt-1",
            opportunity_id="opp-1",
            event_type="CASH_RECEIVED",
            amount_cents=4000,
            occurred_at="2026-08-25T12:00:00+00:00",
            evidence_sha256="c" * 64,
        )
        self.payout = WhopBountyPayoutReconciliationResult(
            provenance=self.provenance_record,
            reconciled_event=self.reconciled,
        )
        self.directive = ScalingDirective(
            opportunity_id="opp-1",
            action="KEEP",
            may_schedule=True,
            max_new_jobs=1,
            reasons=("POSITIVE_REALIZED_PROFIT",),
            realized_cash_eur=40.0,
            reconciled_cost_eur=5.0,
            realized_profit_eur=35.0,
            sample_count=1,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @mock.patch("workflow_os.whop_bounty_settlement_feedback.scaling_directive")
    @mock.patch(
        "workflow_os.whop_bounty_settlement_feedback.reconcile_whop_bounty_payout_to_scaling_truth"
    )
    def test_verified_payout_drives_bounded_scaling_from_reconciled_identity(
        self, reconcile, decide
    ) -> None:
        reconcile.return_value = self.payout
        decide.return_value = self.directive

        result = reconcile_whop_bounty_payout_and_decide_next_action(
            audit_ledger=self.audit,
            provenance_ledger=self.provenance,
            reconciliation_ledger=self.reconciliation,
            evidence=self.evidence,
            settlement_evidence_sha256="c" * 64,
            keep_jobs=1,
            scale_jobs=2,
        )

        self.assertEqual(self.payout, result.payout)
        self.assertEqual(self.directive, result.scaling)
        reconcile.assert_called_once_with(
            audit_ledger=self.audit,
            provenance_ledger=self.provenance,
            reconciliation_ledger=self.reconciliation,
            evidence=self.evidence,
            settlement_evidence_sha256="c" * 64,
        )
        decide.assert_called_once_with(
            self.reconciliation,
            "opp-1",
            experiment_jobs=1,
            keep_jobs=1,
            scale_jobs=2,
            min_samples_to_scale=3,
            min_realized_profit_to_scale_eur=25.0,
        )

    @mock.patch("workflow_os.whop_bounty_settlement_feedback.scaling_directive")
    @mock.patch(
        "workflow_os.whop_bounty_settlement_feedback.reconcile_whop_bounty_payout_to_scaling_truth"
    )
    def test_provenance_identity_drift_blocks_before_scaling(self, reconcile, decide) -> None:
        reconcile.return_value = WhopBountyPayoutReconciliationResult(
            provenance=WhopBountySubmissionProvenance(
                opportunity_id="opp-other",
                bounty_id="bnty_example123",
                side_effect_idempotency_key="side-1",
                side_effect_request_fingerprint="b" * 64,
                submission_target="https://api.whop.com/api/v1/bounty_submissions",
                submission_reference="btys_submission123",
            ),
            reconciled_event=self.reconciled,
        )

        with self.assertRaisesRegex(RuntimeError, "provenance drifted"):
            reconcile_whop_bounty_payout_and_decide_next_action(
                audit_ledger=self.audit,
                provenance_ledger=self.provenance,
                reconciliation_ledger=self.reconciliation,
                evidence=self.evidence,
                settlement_evidence_sha256="c" * 64,
            )
        decide.assert_not_called()

    @mock.patch("workflow_os.whop_bounty_settlement_feedback.scaling_directive")
    @mock.patch(
        "workflow_os.whop_bounty_settlement_feedback.reconcile_whop_bounty_payout_to_scaling_truth"
    )
    def test_scaling_identity_drift_fails_closed(self, reconcile, decide) -> None:
        reconcile.return_value = self.payout
        decide.return_value = ScalingDirective(
            opportunity_id="opp-other",
            action="KEEP",
            may_schedule=True,
            max_new_jobs=1,
            reasons=("POSITIVE_REALIZED_PROFIT",),
            realized_cash_eur=40.0,
            reconciled_cost_eur=5.0,
            realized_profit_eur=35.0,
            sample_count=1,
        )

        with self.assertRaisesRegex(RuntimeError, "scaling directive identity"):
            reconcile_whop_bounty_payout_and_decide_next_action(
                audit_ledger=self.audit,
                provenance_ledger=self.provenance,
                reconciliation_ledger=self.reconciliation,
                evidence=self.evidence,
                settlement_evidence_sha256="c" * 64,
            )


if __name__ == "__main__":
    unittest.main()
