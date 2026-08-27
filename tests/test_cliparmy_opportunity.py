from datetime import datetime, timezone
import unittest

from workflow_os.adapters.contracts import DiscoveryRecord
from workflow_os.cliparmy_opportunity import (
    TrustedClipArmyCampaignEvidence,
    build_cliparmy_opportunity,
)
from workflow_os.opportunities import evaluate, normalize


class ClipArmyOpportunityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 27, 3, 0, tzinfo=timezone.utc)
        self.record = DiscoveryRecord(
            source_platform="cliparmy",
            campaign_id="campaign-123",
            title="Example campaign",
            canonical_url="https://cliparmy.nl/campaign/example",
            observed_at="2026-08-27T02:55:00+00:00",
            raw_evidence_sha256="a" * 64,
            fields={
                "machine_submission_verified": False,
                "zero_touch_execution_enabled": False,
                "execution_block_reason": "official_creator_machine_submission_interface_not_verified",
            },
        )
        self.evidence = TrustedClipArmyCampaignEvidence(
            rights_verified=True,
            source_material_rights_verified=True,
            campaign_brief_verified=True,
            payout_terms_verified=True,
            allowed_platforms_verified=True,
            content_category="general_content",
            usage_rights="Campaign briefing grants clip usage of supplied source material.",
            compliance_risk="LOW",
            platform_risk="MEDIUM",
            duplicate_conflict_status="CLEAR",
            expected_revenue_eur=40.0,
            expected_production_cost_eur=5.0,
            expected_laptop_minutes=20.0,
            estimated_success_probability=0.6,
            probability_collection=0.8,
            expected_time_to_cash_hours=168.0,
            automation_completeness=0.8,
            capital_required_eur=0.0,
            remaining_budget_eur=500.0,
            payout_cap_eur=100.0,
            payout_formula="Verified approved views multiplied by the campaign CPM.",
            payment_method="Clip Army platform payout after campaign approval.",
            approval_rules="Only approved clips and verified views qualify.",
            originality_requirements="Follow the campaign briefing and use permitted source material.",
            allowed_platforms=("tiktok", "instagram"),
            deadline="2026-09-03T00:00:00+00:00",
            freshness_ttl_seconds=3600,
            evidence_sha256="b" * 64,
        )

    def test_verified_campaign_enters_manager_but_pauses_for_execution_gap(self) -> None:
        raw = build_cliparmy_opportunity(self.record, self.evidence)
        normalized = normalize(raw, now=self.now)
        decision = evaluate(normalized, now=self.now)

        self.assertFalse(raw["machine_submission_verified"])
        self.assertFalse(raw["zero_touch_execution_enabled"])
        self.assertEqual(raw["expected_owner_minutes"], 0.0)
        self.assertEqual(decision.decision, "PAUSE")
        self.assertFalse(decision.eligible_for_queue)
        self.assertIn("OWNER_ATTENTION_EXCEPTION", decision.decision_reasons)

    def test_incomplete_rights_evidence_fails_before_opportunity_manager(self) -> None:
        evidence = TrustedClipArmyCampaignEvidence(
            **{**self.evidence.__dict__, "rights_verified": False}
        )
        with self.assertRaisesRegex(ValueError, "evidence is incomplete"):
            build_cliparmy_opportunity(self.record, evidence)

    def test_expected_revenue_cannot_exceed_verified_payout_cap(self) -> None:
        evidence = TrustedClipArmyCampaignEvidence(
            **{**self.evidence.__dict__, "expected_revenue_eur": 101.0}
        )
        with self.assertRaisesRegex(ValueError, "payout cap"):
            build_cliparmy_opportunity(self.record, evidence)

    def test_expected_revenue_cannot_exceed_remaining_budget(self) -> None:
        evidence = TrustedClipArmyCampaignEvidence(
            **{**self.evidence.__dict__, "expected_revenue_eur": 40.0, "remaining_budget_eur": 20.0}
        )
        with self.assertRaisesRegex(ValueError, "remaining budget"):
            build_cliparmy_opportunity(self.record, evidence)

    def test_hostile_discovery_cannot_reenable_execution(self) -> None:
        record = DiscoveryRecord(
            **{
                **self.record.__dict__,
                "fields": {
                    "machine_submission_verified": True,
                    "zero_touch_execution_enabled": True,
                    "execution_block_reason": "",
                },
            }
        )
        with self.assertRaisesRegex(ValueError, "must not assert machine submission"):
            build_cliparmy_opportunity(record, self.evidence)

    def test_stale_evidence_cannot_be_declared_long_lived(self) -> None:
        evidence = TrustedClipArmyCampaignEvidence(
            **{**self.evidence.__dict__, "freshness_ttl_seconds": 86_401}
        )
        with self.assertRaisesRegex(ValueError, "24 hours"):
            build_cliparmy_opportunity(self.record, evidence)

    def test_prohibited_category_is_rejected_at_bridge(self) -> None:
        evidence = TrustedClipArmyCampaignEvidence(
            **{**self.evidence.__dict__, "content_category": "fake_engagement"}
        )
        with self.assertRaisesRegex(ValueError, "prohibited opportunity category"):
            build_cliparmy_opportunity(self.record, evidence)


if __name__ == "__main__":
    unittest.main()
