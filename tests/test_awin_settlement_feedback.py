from __future__ import annotations

from dataclasses import replace
import tempfile
import unittest
from pathlib import Path

from workflow_os.audit import AuditRevenueLedger
from workflow_os.awin_settlement_feedback import (
    reconcile_awin_payout_and_decide_next_action,
)
from workflow_os.awin_transaction_evidence import (
    AwinTransactionEvidence,
    record_awin_transaction_evidence,
)
from workflow_os.plaid_bank_receipt import normalize_plaid_bank_receipt
from workflow_os.reconciliation import RevenueReconciliationLedger


class _KnownOpportunityLedger:
    def latest_decision(self, opportunity_id):
        if opportunity_id == "opp-awin-1":
            return {"opportunity_id": opportunity_id, "decision": "ACCEPT"}
        return None


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
            "payment_evidence_sha256": "b" * 64,
        }
        payload.update(overrides)
        return payload

    def _bank_receipt(self, **overrides):
        payload = {
            "transaction_id": "plaid-bank-tx-77",
            "account_id": "settlement-account-1",
            "amount": "-42.00",
            "iso_currency_code": "EUR",
            "unofficial_currency_code": None,
            "date": "2026-08-25",
            "name": "AWIN PAYMENT pay-77",
            "pending": False,
        }
        payload.update(overrides)
        return normalize_plaid_bank_receipt(payload)

    def _record_transaction(self, audit_ledger, transaction):
        return record_awin_transaction_evidence(
            {
                "transaction_id": transaction.transaction_id,
                "publisher_id": transaction.publisher_id,
                "advertiser_id": transaction.advertiser_id,
                "status": transaction.status,
                "commission_eur": f"{transaction.commission_cents / 100:.2f}",
                "currency": transaction.currency,
                "transaction_at": transaction.transaction_at,
                "validation_at": transaction.validation_at,
                "click_ref": transaction.click_ref,
                "evidence_sha256": transaction.evidence_sha256,
            },
            expected_opportunity_id=transaction.opportunity_id,
            opportunity_ledger=_KnownOpportunityLedger(),
            audit_ledger=audit_ledger,
        )

    def _reconcile(
        self,
        ledger,
        *,
        payout=None,
        transaction=None,
        bank_receipt=None,
        account_id="settlement-account-1",
        audit_ledger=None,
        record_transaction=True,
    ):
        transaction = self._transaction() if transaction is None else transaction
        if audit_ledger is None:
            audit_ledger = AuditRevenueLedger(Path(ledger.path).with_name("audit.sqlite"))
        if record_transaction:
            self._record_transaction(audit_ledger, transaction)
        return reconcile_awin_payout_and_decide_next_action(
            self._payout() if payout is None else payout,
            transaction=transaction,
            bank_receipt=self._bank_receipt() if bank_receipt is None else bank_receipt,
            expected_bank_account_id=account_id,
            audit_ledger=audit_ledger,
            reconciliation_ledger=ledger,
        )

    def test_received_payout_enters_reconciliation_truth_and_bounded_scaling(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RevenueReconciliationLedger(Path(tmp) / "reconciliation.sqlite")
            result = self._reconcile(ledger)

            self.assertEqual(result.reconciled_event.event_type, "CASH_RECEIVED")
            self.assertEqual(result.reconciled_event.amount_cents, 4200)
            self.assertEqual(result.reconciled_event.opportunity_id, "opp-awin-1")
            self.assertEqual(result.payout.bank_reference, "plaid-bank-tx-77")
            self.assertEqual(result.payout.bank_evidence_sha256, self._bank_receipt().evidence_sha256)
            self.assertEqual(result.scaling.opportunity_id, "opp-awin-1")
            self.assertEqual(result.scaling.sample_count, 1)
            self.assertAlmostEqual(result.scaling.realized_cash_eur, 42.0)
            self.assertIn(result.scaling.action, {"KEEP", "SCALE"})

    def test_exact_replay_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RevenueReconciliationLedger(Path(tmp) / "reconciliation.sqlite")
            first = self._reconcile(ledger)
            second = self._reconcile(ledger)
            self.assertEqual(first.reconciled_event, second.reconciled_event)
            self.assertEqual(ledger.realized_summary("opp-awin-1").sample_count, 1)

    def test_missing_typed_bank_receipt_cannot_enter_cash_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RevenueReconciliationLedger(Path(tmp) / "reconciliation.sqlite")
            with self.assertRaisesRegex(TypeError, "bank_receipt"):
                self._reconcile(ledger, bank_receipt="not-evidence")
            self.assertEqual(ledger.realized_summary("opp-awin-1").sample_count, 0)

    def test_forged_typed_bank_receipt_digest_cannot_enter_cash_truth(self):
        forged = replace(self._bank_receipt(), evidence_sha256="0" * 64)
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RevenueReconciliationLedger(Path(tmp) / "reconciliation.sqlite")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                self._reconcile(ledger, bank_receipt=forged)
            self.assertEqual(ledger.realized_summary("opp-awin-1").sample_count, 0)

    def test_unrecorded_typed_awin_transaction_cannot_enter_cash_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RevenueReconciliationLedger(Path(tmp) / "reconciliation.sqlite")
            forged = replace(self._transaction(), evidence_sha256="f" * 64)
            with self.assertRaisesRegex(ValueError, "missing immutable audit evidence"):
                self._reconcile(
                    ledger,
                    transaction=forged,
                    record_transaction=False,
                )
            self.assertEqual(ledger.realized_summary("opp-awin-1").sample_count, 0)

    def test_typed_awin_transaction_must_exactly_match_recorded_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RevenueReconciliationLedger(Path(tmp) / "reconciliation.sqlite")
            audit = AuditRevenueLedger(Path(tmp) / "audit.sqlite")
            original = self._transaction()
            self._record_transaction(audit, original)
            forged = replace(original, commission_cents=9900)
            with self.assertRaisesRegex(ValueError, "does not match immutable audit evidence"):
                self._reconcile(
                    ledger,
                    transaction=forged,
                    audit_ledger=audit,
                    record_transaction=False,
                )
            self.assertEqual(ledger.realized_summary("opp-awin-1").sample_count, 0)

    def test_non_approved_transaction_cannot_be_promoted_to_cash(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RevenueReconciliationLedger(Path(tmp) / "reconciliation.sqlite")
            with self.assertRaisesRegex(ValueError, "only approved"):
                self._reconcile(ledger, transaction=self._transaction(status="pending"))
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
                    self._reconcile(ledger, payout=payload)
                self.assertEqual(ledger.realized_summary("opp-awin-1").sample_count, 0)

    def test_plaid_receipt_must_match_amount_and_configured_account(self):
        cases = (
            (self._bank_receipt(amount="-41.99"), "amount/currency"),
            (self._bank_receipt(account_id="other-account"), "configured settlement account"),
        )
        for bank_receipt, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                ledger = RevenueReconciliationLedger(Path(tmp) / "reconciliation.sqlite")
                with self.assertRaisesRegex(ValueError, expected):
                    self._reconcile(ledger, bank_receipt=bank_receipt)
                self.assertEqual(ledger.realized_summary("opp-awin-1").sample_count, 0)

    def test_bank_receipt_cannot_predate_awin_payment(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RevenueReconciliationLedger(Path(tmp) / "reconciliation.sqlite")
            with self.assertRaisesRegex(ValueError, "cannot predate"):
                self._reconcile(ledger, bank_receipt=self._bank_receipt(date="2026-08-24"))
            self.assertEqual(ledger.realized_summary("opp-awin-1").sample_count, 0)

    def test_bank_description_must_bind_exact_awin_payment_identity(self):
        cases = (
            ("AWIN PAYMENT pay-78", "exact Awin payment identity"),
            ("AWIN PAYMENT xpay-77x", "exact Awin payment identity"),
        )
        for description, expected in cases:
            with self.subTest(description=description), tempfile.TemporaryDirectory() as tmp:
                ledger = RevenueReconciliationLedger(Path(tmp) / "reconciliation.sqlite")
                with self.assertRaisesRegex(ValueError, expected):
                    self._reconcile(
                        ledger,
                        bank_receipt=self._bank_receipt(name=description),
                    )
                self.assertEqual(ledger.realized_summary("opp-awin-1").sample_count, 0)

    def test_caller_supplied_bank_hash_or_reference_cannot_override_plaid_evidence(self):
        payout = self._payout(
            bank_reference="forged-reference",
            bank_evidence_sha256="c" * 64,
            bank_received_at="2099-01-01T00:00:00+00:00",
        )
        with tempfile.TemporaryDirectory() as tmp:
            ledger = RevenueReconciliationLedger(Path(tmp) / "reconciliation.sqlite")
            result = self._reconcile(ledger, payout=payout)
            self.assertEqual(result.payout.bank_reference, "plaid-bank-tx-77")
            self.assertNotEqual(result.payout.bank_evidence_sha256, "c" * 64)
            self.assertEqual(result.payout.bank_received_at, "2026-08-25T00:00:00+00:00")

    def test_hostile_or_unverifiable_payout_evidence_fails_closed(self):
        cases = (
            (self._payout(currency="USD"), "EUR only"),
            (self._payout(amount_eur=True), "positive finite"),
            (self._payout(payment_evidence_sha256="BAD"), "payment_evidence_sha256"),
        )
        for payload, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                ledger = RevenueReconciliationLedger(Path(tmp) / "reconciliation.sqlite")
                with self.assertRaisesRegex(ValueError, expected):
                    self._reconcile(ledger, payout=payload)
                self.assertEqual(ledger.realized_summary("opp-awin-1").sample_count, 0)


if __name__ == "__main__":
    unittest.main()
