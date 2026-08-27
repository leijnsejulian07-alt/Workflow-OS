import tempfile
import unittest
from pathlib import Path

from workflow_os.reconciliation import RevenueReconciliationLedger
from workflow_os.website_fulfillment_gate import WebsitePaymentEvidence, WebsiteScopeSnapshot
from workflow_os.website_handoff_execution import WebsiteDeliveryProvenance
from workflow_os.website_settlement_feedback import (
    reconcile_delivered_website_payment_and_decide_next_action,
)


class WebsiteSettlementFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = RevenueReconciliationLedger(Path(self.tmp.name) / "reconciliation.sqlite")
        self.snapshot = WebsiteScopeSnapshot(
            opportunity_id="website-op-1",
            lead_id="lead-1",
            pages=3,
            fixed_price_eur=350.0,
            quote_expires_at="2026-08-30T12:00:00+00:00",
            usage_rights="customer_attested",
            customer_controls_domain=True,
            recurring_maintenance=False,
            mobile_responsive=True,
            basic_seo_metadata=True,
            contact_or_cta=True,
            payment_method="invoice",
            approval_rules="fixed scope",
            source_checked_at="2026-08-27T12:00:00+00:00",
            snapshot_sha256="a" * 64,
        )
        self.payment = WebsitePaymentEvidence(
            opportunity_id="website-op-1",
            amount_eur=350.0,
            currency="EUR",
            payment_reference="pay-website-1",
            received_at="2026-08-27T13:00:00+00:00",
            evidence_sha256="b" * 64,
            payment_received=True,
        )
        self.delivery = WebsiteDeliveryProvenance(
            opportunity_id="website-op-1",
            scope_sha256="a" * 64,
            manifest_sha256="c" * 64,
            side_effect_idempotency_key="website-handoff:1",
            side_effect_request_fingerprint="d" * 64,
            delivery_target="CUSTOMER_DOWNLOAD",
            delivery_reference="delivery-1",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_confirmed_delivery_promotes_payment_to_reconciled_cash_and_keep(self):
        result = reconcile_delivered_website_payment_and_decide_next_action(
            reconciliation_ledger=self.ledger,
            snapshot=self.snapshot,
            payment=self.payment,
            delivery=self.delivery,
        )
        self.assertEqual(result.reconciled_event.event_type, "CASH_RECEIVED")
        self.assertEqual(result.reconciled_event.amount_cents, 35000)
        self.assertEqual(result.scaling.opportunity_id, "website-op-1")
        self.assertEqual(result.scaling.action, "KEEP")
        self.assertTrue(result.scaling.may_schedule)
        summary = self.ledger.realized_summary("website-op-1")
        self.assertEqual(summary.realized_cash_eur, 350.0)
        self.assertEqual(summary.sample_count, 1)

    def test_exact_replay_is_idempotent(self):
        first = reconcile_delivered_website_payment_and_decide_next_action(
            reconciliation_ledger=self.ledger,
            snapshot=self.snapshot,
            payment=self.payment,
            delivery=self.delivery,
        )
        second = reconcile_delivered_website_payment_and_decide_next_action(
            reconciliation_ledger=self.ledger,
            snapshot=self.snapshot,
            payment=self.payment,
            delivery=self.delivery,
        )
        self.assertEqual(first.reconciled_event, second.reconciled_event)
        self.assertEqual(self.ledger.realized_summary("website-op-1").sample_count, 1)

    def test_delivery_identity_drift_fails_closed_before_cash_write(self):
        drifted = WebsiteDeliveryProvenance(
            opportunity_id="different-opportunity",
            scope_sha256=self.delivery.scope_sha256,
            manifest_sha256=self.delivery.manifest_sha256,
            side_effect_idempotency_key=self.delivery.side_effect_idempotency_key,
            side_effect_request_fingerprint=self.delivery.side_effect_request_fingerprint,
            delivery_target=self.delivery.delivery_target,
            delivery_reference=self.delivery.delivery_reference,
        )
        with self.assertRaisesRegex(ValueError, "delivery opportunity identity mismatch"):
            reconcile_delivered_website_payment_and_decide_next_action(
                reconciliation_ledger=self.ledger,
                snapshot=self.snapshot,
                payment=self.payment,
                delivery=drifted,
            )
        self.assertEqual(self.ledger.realized_summary("website-op-1").sample_count, 0)

    def test_scope_drift_fails_closed_before_cash_write(self):
        drifted = WebsiteDeliveryProvenance(
            opportunity_id=self.delivery.opportunity_id,
            scope_sha256="e" * 64,
            manifest_sha256=self.delivery.manifest_sha256,
            side_effect_idempotency_key=self.delivery.side_effect_idempotency_key,
            side_effect_request_fingerprint=self.delivery.side_effect_request_fingerprint,
            delivery_target=self.delivery.delivery_target,
            delivery_reference=self.delivery.delivery_reference,
        )
        with self.assertRaisesRegex(ValueError, "delivery scope identity mismatch"):
            reconcile_delivered_website_payment_and_decide_next_action(
                reconciliation_ledger=self.ledger,
                snapshot=self.snapshot,
                payment=self.payment,
                delivery=drifted,
            )
        self.assertEqual(self.ledger.realized_summary("website-op-1").sample_count, 0)

    def test_unconfirmed_or_underpaid_payment_cannot_become_scaling_truth(self):
        unconfirmed = WebsitePaymentEvidence(
            opportunity_id=self.payment.opportunity_id,
            amount_eur=self.payment.amount_eur,
            currency=self.payment.currency,
            payment_reference=self.payment.payment_reference,
            received_at=self.payment.received_at,
            evidence_sha256=self.payment.evidence_sha256,
            payment_received=False,
        )
        with self.assertRaisesRegex(ValueError, "unconfirmed website payment"):
            reconcile_delivered_website_payment_and_decide_next_action(
                reconciliation_ledger=self.ledger,
                snapshot=self.snapshot,
                payment=unconfirmed,
                delivery=self.delivery,
            )

        underpaid = WebsitePaymentEvidence(
            opportunity_id=self.payment.opportunity_id,
            amount_eur=249.0,
            currency="EUR",
            payment_reference="pay-under",
            received_at=self.payment.received_at,
            evidence_sha256="f" * 64,
            payment_received=True,
        )
        with self.assertRaisesRegex(ValueError, "below immutable fixed price"):
            reconcile_delivered_website_payment_and_decide_next_action(
                reconciliation_ledger=self.ledger,
                snapshot=self.snapshot,
                payment=underpaid,
                delivery=self.delivery,
            )
        self.assertEqual(self.ledger.realized_summary("website-op-1").sample_count, 0)


if __name__ == "__main__":
    unittest.main()
