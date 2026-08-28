from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workflow_os.awin_settlement_feedback import (
    reconcile_awin_payout_and_decide_next_action,
)
from workflow_os.awin_transaction_evidence import AwinTransactionEvidence
from workflow_os.reconciliation import RevenueReconciliationLedger


class AwinSettlementFeedbackTests(unittest.TestCase):
    def _transaction(self, *, status: str = "approved", commission_cents: int = 4200):
        return AwinTransactionEvidence(
            transaction_id="txn-123",
            opportunity_id="opp-awin-1",
            publisher_id=101,
            advertiser_id=202,
            status=status,
            commission_cents=commission_cents,
            currency="EUR",
            transaction_at="2026-08-20T12:00:00+00:00",
            validation_at="2026-08-22T12:00:00+00:00" if status != "pending" else None,
            click_ref="workflow-os:opp-awin-1",
            evidence_sha256="a" * 64,
        )

    def _payout(self, **overrides):
        payload = {
            "payment_id": "pay-77",
            "transaction_id": "txn-123",
            "opportunity_id": "opp-awin-1",
            "publisher_id": 101,
            "amount_eur": "42.00",
            "currency": "EUR",
            "paid_at": "2026-08-25T08:00:00+00:00",
            "bank_received_at": "2026-08-25T10:00:00+00:00",
            "bank_reference": "bank-ref-77",
            "payment_evidence_sha256": "b" * 64,
            "bank_evidence_sha256": "c" * 64,
        }
        payload.update(overrides)
        return payload

    def test_received_payout_enters_reconciliation_truth_and_bounded_scaling(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RevenueReconciliationLedger(Path(tmp) / "reconciliation.sqlite")
            result = reconcile_awin_payout_and_decide_next_action(
                self._payout(),
                transaction=self._transaction(),
                reconciliation_ledger=ledger,
            )

            self.assertEqual(result.reconciled_event.event_type, "CASH_RECEIVED")
            self.assertEqual(result.reconciled_event.amount_cents, 4200)
            self.assertEqual(result.reconciled_event.opportunity_id, "opp-awin-1")
            self.assertEqual(result.scaling.opportunity_id, "opp-awin-1")
            self.assertEqual(result.scaling.sample_count, 1)
            self.assertAlmostEqual(result.scaling.realized_cash_eur, 42.0)
            self.assertIn(result.scaling.action, {"KEEP", "SCALE"})

    def test_exact_replay_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RevenueReconciliationLedger(Path(tmp) / "reconciliation.sqlite")
            first = reconcile_awin_payout_and_decide_next_action(
                self._payout(),
                transaction=self._transaction(),
                reconciliation_ledger=ledger,
            )
            second = reconcile_awin_payout_and_decide_next_action(
                self._payout(),
                transaction=self._transaction(),
                reconciliation_ledger=ledger,
            )
            self.assertEqual(first.reconciled_event, second.reconciled_event)
            self.assertEqual(ledger.realized_summary("opp-awin-1").sample_count, 1)

    def test_approved_commission_without_received_payout_does_not_enter_cash_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RevenueReconciliationLedger(Path(tmp) / "reconciliation.sqlite")
            bad = self._payout(bank_received_at=None)
            with self.assertRaisesRegex(ValueError, "bank_received_at"):
                reconcile_awin_payout_and_decide_next_action(
                    bad,
                    transaction=self._transaction(),
                    reconciliation_ledger=ledger,
                )
            self.assertEqual(ledger.realized_summary("opp-awin-1").sample_count, 0)

    def test_non_approved_transaction_cannot_be_promoted_to_cash(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RevenueReconciliationLedger(Path(tmp) / "reconciliation.sqlite")
            with self.assertRaisesRegex(ValueError, "only approved"):
                reconcile_awin_payout_and_decide_next_action(
                    self._payout(),
                    transaction=self._transaction(status="pending"),
                    reconciliation_ledger=ledger,
                )
            self.assertEqual(ledger.realized_summary("opp-awin-1").sample_count, 0)

    def test_payout_identity_and_amount_must_match_transaction(self):
        cases = (
            (self._payout(transaction_id="txn-other"), "transaction identity mismatch"),
            (self._payout(opportunity_id="opp-other"), "opportunity identity mismatch"),
            (self._payout(publisher_id=999), "publisher identity mismatch"),
            (self._payout(amount_eur="41.99"), "amount does not match"),
        )
        for payload, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                ledger = RevenueReconciliationLedger(Path(tmp) / "reconciliation.sqlite")
                with self.assertRaisesRegex(ValueError, expected):
                    reconcile_awin_payout_and_decide_next_action(
                        payload,
                        transaction=self._transaction(),
                        reconciliation_ledger=ledger,
                    )
                self.assertEqual(ledger.realized_summary("opp-awin-1").sample_count, 0)

    def test_bank_receipt_cannot_predate_awin_payment(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RevenueReconciliationLedger(Path(tmp) / "reconciliation.sqlite")
            with self.assertRaisesRegex(ValueError, "cannot predate"):
                reconcile_awin_payout_and_decide_next_action(
                    self._payout(bank_received_at="2026-08-25T07:59:59+00:00"),
                    transaction=self._transaction(),
                    reconciliation_ledger=ledger,
                )
            self.assertEqual(ledger.realized_summary("opp-awin-1").sample_count, 0)

    def test_hostile_or_unverifiable_payout_evidence_fails_closed(self):
        cases = (
            (self._payout(currency="USD"), "EUR only"),
            (self._payout(amount_eur=True), "positive finite"),
            (self._payout(payment_evidence_sha256="BAD"), "payment_evidence_sha256"),
            (self._payout(bank_evidence_sha256="BAD"), "bank_evidence_sha256"),
        )
        for payload, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                ledger = RevenueReconciliationLedger(Path(tmp) / "reconciliation.sqlite")
                with self.assertRaisesRegex(ValueError, expected):
                    reconcile_awin_payout_and_decide_next_action(
                        payload,
                        transaction=self._transaction(),
                        reconciliation_ledger=ledger,
                    )
                self.assertEqual(ledger.realized_summary("opp-awin-1").sample_count, 0)


if __name__ == "__main__":
    unittest.main()
