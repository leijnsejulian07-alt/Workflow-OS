import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from workflow_os.side_effects import SideEffectLedger
from workflow_os.website_fulfillment_gate import FulfillmentGateDecision, WebsiteScopeSnapshot
from workflow_os.website_handoff_reservation import WebsiteHandoffIntent, reserve_website_handoff
from workflow_os.website_static_build import (
    StaticPageInput,
    WebsiteContentSpec,
    build_static_site,
    qa_static_site,
)


class WebsiteHandoffReservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = SideEffectLedger(Path(self.tmp.name) / "effects.sqlite")
        self.snapshot = WebsiteScopeSnapshot(
            opportunity_id="website:test:handoff",
            lead_id="lead-2",
            pages=1,
            fixed_price_eur=300.0,
            quote_expires_at="2026-09-01T12:00:00+00:00",
            usage_rights="customer_attested_owned_or_licensed_content",
            customer_controls_domain=True,
            recurring_maintenance=False,
            mobile_responsive=True,
            basic_seo_metadata=True,
            contact_or_cta=True,
            payment_method="invoice_or_supported_payment_link",
            approval_rules="fixed_scope_no_recurring_maintenance",
            source_checked_at="2026-08-27T10:00:00+00:00",
            snapshot_sha256="c" * 64,
        )
        gate = FulfillmentGateDecision(
            state="READY_FOR_BOUNDED_BUILD",
            reason="PAYMENT_EVIDENCE_ACCEPTED_NOT_YET_RECONCILED_AS_REVENUE",
            opportunity_id=self.snapshot.opportunity_id,
            scope_sha256=self.snapshot.snapshot_sha256,
            payment_reference="pay-2",
        )
        content = WebsiteContentSpec(
            site_title="Klant",
            description="Kleine vaste website.",
            pages=(StaticPageInput("index", "Home", "Welkom."),),
            contact_label="Mail ons",
            contact_href="mailto:klant@example.com",
        )
        self.artifact = build_static_site(self.snapshot, gate, content)
        self.qa = qa_static_site(self.snapshot, self.artifact)
        self.intent = WebsiteHandoffIntent(
            opportunity_id=self.snapshot.opportunity_id,
            scope_sha256=self.snapshot.snapshot_sha256,
            manifest_sha256=self.artifact.manifest_sha256,
            handoff_mode="CUSTOMER_DOWNLOAD",
            customer_controls_domain=True,
            customer_controls_hosting=True,
            target_reference="customer-controlled-download:lead-2",
        )

    def test_qa_pass_reserves_only_without_beginning_execution(self):
        result = reserve_website_handoff(self.snapshot, self.artifact, self.qa, self.intent, self.ledger)
        self.assertEqual(result.state, "RESERVED_ONLY_NO_EXTERNAL_ACTION")
        self.assertIsNotNone(result.side_effect)
        self.assertEqual(result.side_effect.state, "RESERVED")
        self.assertEqual(result.side_effect.attempt_count, 0)

    def test_exact_replay_is_idempotent(self):
        first = reserve_website_handoff(self.snapshot, self.artifact, self.qa, self.intent, self.ledger)
        second = reserve_website_handoff(self.snapshot, self.artifact, self.qa, self.intent, self.ledger)
        self.assertEqual(first.idempotency_key, second.idempotency_key)
        self.assertEqual(second.side_effect.state, "RESERVED")
        self.assertEqual(second.side_effect.attempt_count, 0)

    def test_qa_hold_creates_no_side_effect(self):
        held = replace(self.qa, state="HOLD", reason="BROKEN_INTERNAL_LINK")
        result = reserve_website_handoff(self.snapshot, self.artifact, held, self.intent, self.ledger)
        self.assertEqual(result.state, "HOLD")
        self.assertIsNone(result.side_effect)

    def test_customer_control_is_required(self):
        result = reserve_website_handoff(
            self.snapshot,
            self.artifact,
            self.qa,
            replace(self.intent, customer_controls_hosting=False),
            self.ledger,
        )
        self.assertEqual(result.state, "HOLD")
        self.assertEqual(result.reason, "CUSTOMER_CONTROLLED_HOSTING_REQUIRED")

    def test_identity_drift_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            reserve_website_handoff(
                self.snapshot,
                self.artifact,
                self.qa,
                replace(self.intent, opportunity_id="website:other"),
                self.ledger,
            )

    def test_same_idempotency_identity_cannot_change_target(self):
        reserve_website_handoff(self.snapshot, self.artifact, self.qa, self.intent, self.ledger)
        with self.assertRaisesRegex(ValueError, "different side effect"):
            reserve_website_handoff(
                self.snapshot,
                self.artifact,
                self.qa,
                replace(self.intent, target_reference="customer-controlled-download:other"),
                self.ledger,
            )

    def test_unsupported_handoff_mode_does_not_reserve(self):
        result = reserve_website_handoff(
            self.snapshot,
            self.artifact,
            self.qa,
            replace(self.intent, handoff_mode="BROWSER_AUTOMATION"),
            self.ledger,
        )
        self.assertEqual(result.state, "HOLD")
        self.assertEqual(result.reason, "UNSUPPORTED_HANDOFF_MODE")
        self.assertIsNone(result.side_effect)


if __name__ == "__main__":
    unittest.main()
