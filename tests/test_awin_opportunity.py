from datetime import datetime, timezone
import unittest

from workflow_os.awin_opportunity import TrustedAwinProgramEvidence, build_awin_opportunity
from workflow_os.opportunities import evaluate, normalize


class AwinOpportunityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 28, 7, 0, tzinfo=timezone.utc)
        self.evidence = TrustedAwinProgramEvidence(
            publisher_id=12345,
            advertiser_id=67890,
            program_name="Example Merchant",
            program_approved=True,
            terms_verified=True,
            promotional_channel="CONTENT",
            promotional_channel_approved=True,
            content_category="general_content",
            usage_rights="Publisher may create original editorial content using approved affiliate links.",
            disclosure_requirements=("Clearly disclose the commercial affiliate relationship.",),
            commission_model="CPA",
            commission_rate=10.0,
            commission_rate_is_percent=True,
            average_order_value_eur=50.0,
            expected_clicks=1000.0,
            expected_conversion_rate=0.02,
            expected_approval_rate=0.8,
            expected_production_cost_eur=10.0,
            expected_laptop_minutes=30.0,
            expected_time_to_cash_hours=720.0,
            automation_completeness=0.9,
            capital_required_eur=0.0,
            compliance_risk="LOW",
            platform_risk="LOW",
            duplicate_conflict_status="CLEAR",
            cookie_window_days=30,
            payment_method="Awin publisher payout after advertiser validation and payment.",
            approval_rules="Only validated transactions under the approved advertiser program qualify.",
            originality_requirements="Original, non-spam promotional content compliant with program terms.",
            observed_at="2026-08-28T06:55:00+00:00",
            deadline="2026-09-28T00:00:00+00:00",
            freshness_ttl_seconds=3600,
            evidence_sha256="a" * 64,
        )

    def test_valid_program_can_enter_and_be_accepted_by_opportunity_manager(self) -> None:
        raw = build_awin_opportunity(self.evidence)
        normalized = normalize(raw, now=self.now)
        decision = evaluate(normalized, now=self.now)

        self.assertEqual(decision.decision, "ACCEPT")
        self.assertTrue(decision.eligible_for_queue)
        self.assertTrue(raw["forecast_only"])
        self.assertFalse(raw["proves_received_cash"])
        self.assertEqual(raw["tracking_click_ref"], f"workflow-os:{raw['opportunity_id']}")
        self.assertAlmostEqual(raw["expected_revenue"], 100.0)

    def test_program_must_be_approved(self) -> None:
        evidence = TrustedAwinProgramEvidence(**{**self.evidence.__dict__, "program_approved": False})
        with self.assertRaisesRegex(ValueError, "not approved"):
            build_awin_opportunity(evidence)

    def test_program_terms_must_be_verified(self) -> None:
        evidence = TrustedAwinProgramEvidence(**{**self.evidence.__dict__, "terms_verified": False})
        with self.assertRaisesRegex(ValueError, "terms are not independently verified"):
            build_awin_opportunity(evidence)

    def test_unapproved_or_unsupported_channel_fails_closed(self) -> None:
        evidence = TrustedAwinProgramEvidence(
            **{**self.evidence.__dict__, "promotional_channel_approved": False}
        )
        with self.assertRaisesRegex(ValueError, "channel is not approved"):
            build_awin_opportunity(evidence)

        evidence = TrustedAwinProgramEvidence(
            **{**self.evidence.__dict__, "promotional_channel": "EMAIL"}
        )
        with self.assertRaisesRegex(ValueError, "unsupported or high-risk"):
            build_awin_opportunity(evidence)

    def test_prohibited_category_fails_before_manager(self) -> None:
        evidence = TrustedAwinProgramEvidence(
            **{**self.evidence.__dict__, "content_category": "spam"}
        )
        with self.assertRaisesRegex(ValueError, "prohibited opportunity category"):
            build_awin_opportunity(evidence)

    def test_invalid_commission_and_probability_fail_closed(self) -> None:
        evidence = TrustedAwinProgramEvidence(
            **{**self.evidence.__dict__, "commission_rate": 101.0}
        )
        with self.assertRaisesRegex(ValueError, "exceeds 100%"):
            build_awin_opportunity(evidence)

        evidence = TrustedAwinProgramEvidence(
            **{**self.evidence.__dict__, "expected_approval_rate": 1.1}
        )
        with self.assertRaisesRegex(ValueError, "within \[0, 1\]"):
            build_awin_opportunity(evidence)

    def test_stale_evidence_cannot_claim_long_ttl(self) -> None:
        evidence = TrustedAwinProgramEvidence(
            **{**self.evidence.__dict__, "freshness_ttl_seconds": 86_401}
        )
        with self.assertRaisesRegex(ValueError, "within 24 hours"):
            build_awin_opportunity(evidence)

    def test_identity_is_stable_and_channel_specific(self) -> None:
        first = build_awin_opportunity(self.evidence)
        replay = build_awin_opportunity(self.evidence)
        search = build_awin_opportunity(
            TrustedAwinProgramEvidence(**{**self.evidence.__dict__, "promotional_channel": "SEARCH"})
        )
        self.assertEqual(first["opportunity_id"], replay["opportunity_id"])
        self.assertNotEqual(first["opportunity_id"], search["opportunity_id"])


if __name__ == "__main__":
    unittest.main()
