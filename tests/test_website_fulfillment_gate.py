from __future__ import annotations

from datetime import datetime, timezone
import unittest

from workflow_os.website_fulfillment_gate import (
    WebsitePaymentEvidence,
    build_scope_snapshot,
    gate_paid_fulfillment,
)


NOW = datetime(2026, 8, 27, 7, 0, tzinfo=timezone.utc)


def opportunity() -> dict[str, object]:
    return {
        "opportunity_id": "website-op-123",
        "campaign_id": "lead-123",
        "category": "website_in_a_box",
        "rights_verification_state": "VERIFIED",
        "usage_rights": "Customer grants rights to use supplied content for this one-time website delivery.",
        "expected_revenue": 350.0,
        "deadline": "2026-08-30T12:00:00+00:00",
        "source_checked_at": "2026-08-27T06:00:00+00:00",
        "payment_method": "verified invoice payment",
        "approval_rules": "Fixed-scope automated QA before deployment",
        "website_scope": {
            "pages": 3,
            "mobile_responsive": True,
            "basic_seo_metadata": True,
            "contact_or_cta": True,
            "recurring_maintenance": False,
            "customer_controls_domain": True,
        },
        "lead_evidence": {
            "explicit_request_for_website": True,
            "commercial_contact_consent": True,
            "recurring_maintenance_requested": False,
            "content_rights_attested": True,
        },
    }


def accepted_decision() -> dict[str, object]:
    return {
        "opportunity_id": "website-op-123",
        "decision": "ACCEPT",
        "eligible_for_queue": True,
    }


def payment(**overrides: object) -> WebsitePaymentEvidence:
    values: dict[str, object] = {
        "opportunity_id": "website-op-123",
        "amount_eur": 350.0,
        "currency": "EUR",
        "payment_reference": "pay_abc123",
        "received_at": "2026-08-27T06:30:00+00:00",
        "evidence_sha256": "a" * 64,
        "payment_received": True,
    }
    values.update(overrides)
    return WebsitePaymentEvidence(**values)  # type: ignore[arg-type]


class WebsiteFulfillmentGateTests(unittest.TestCase):
    def test_accept_creates_deterministic_immutable_scope(self) -> None:
        first = build_scope_snapshot(opportunity(), accepted_decision(), now=NOW)
        second = build_scope_snapshot(opportunity(), accepted_decision(), now=NOW)
        self.assertEqual(first, second)
        self.assertEqual(first.pages, 3)
        self.assertEqual(first.fixed_price_eur, 350.0)
        self.assertFalse(first.recurring_maintenance)
        self.assertTrue(first.customer_controls_domain)
        self.assertEqual(len(first.snapshot_sha256), 64)

    def test_rejects_stale_or_non_queue_eligible_decision(self) -> None:
        decision = accepted_decision()
        decision["decision"] = "PAUSE"
        decision["eligible_for_queue"] = False
        with self.assertRaisesRegex(ValueError, "not queue-eligible ACCEPT"):
            build_scope_snapshot(opportunity(), decision, now=NOW)

    def test_rejects_recurring_maintenance_or_domain_loss(self) -> None:
        recurring = opportunity()
        recurring["website_scope"] = dict(recurring["website_scope"], recurring_maintenance=True)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "recurring maintenance"):
            build_scope_snapshot(recurring, accepted_decision(), now=NOW)

        no_domain = opportunity()
        no_domain["website_scope"] = dict(no_domain["website_scope"], customer_controls_domain=False)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "customer-controlled domain"):
            build_scope_snapshot(no_domain, accepted_decision(), now=NOW)

    def test_rejects_incomplete_consent_or_rights_evidence(self) -> None:
        op = opportunity()
        op["lead_evidence"] = dict(op["lead_evidence"], content_rights_attested=False)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "consent/scope evidence"):
            build_scope_snapshot(op, accepted_decision(), now=NOW)

    def test_confirmed_full_payment_only_allows_bounded_build(self) -> None:
        snapshot = build_scope_snapshot(opportunity(), accepted_decision(), now=NOW)
        result = gate_paid_fulfillment(snapshot, payment(), now=NOW)
        self.assertEqual(result.state, "READY_FOR_BOUNDED_BUILD")
        self.assertIn("NOT_YET_RECONCILED_AS_REVENUE", result.reason)
        self.assertEqual(result.payment_reference, "pay_abc123")

    def test_unpaid_or_underpaid_holds(self) -> None:
        snapshot = build_scope_snapshot(opportunity(), accepted_decision(), now=NOW)
        unpaid = gate_paid_fulfillment(snapshot, payment(payment_received=False), now=NOW)
        self.assertEqual(unpaid.state, "HOLD")
        self.assertEqual(unpaid.reason, "PAYMENT_NOT_CONFIRMED")

        underpaid = gate_paid_fulfillment(snapshot, payment(amount_eur=349.99), now=NOW)
        self.assertEqual(underpaid.state, "HOLD")
        self.assertEqual(underpaid.reason, "PAYMENT_BELOW_FIXED_PRICE")

    def test_payment_identity_and_evidence_fail_closed(self) -> None:
        snapshot = build_scope_snapshot(opportunity(), accepted_decision(), now=NOW)
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            gate_paid_fulfillment(snapshot, payment(opportunity_id="other"), now=NOW)
        with self.assertRaisesRegex(ValueError, "digest is malformed"):
            gate_paid_fulfillment(snapshot, payment(evidence_sha256="bad"), now=NOW)

    def test_payment_after_quote_expiry_holds(self) -> None:
        snapshot = build_scope_snapshot(opportunity(), accepted_decision(), now=NOW)
        result = gate_paid_fulfillment(
            snapshot,
            payment(received_at="2026-08-31T00:00:00+00:00"),
            now=datetime(2026, 8, 31, 1, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(result.state, "HOLD")
        self.assertEqual(result.reason, "PAYMENT_AFTER_QUOTE_EXPIRY")


if __name__ == "__main__":
    unittest.main()
