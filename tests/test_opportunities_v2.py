import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.opportunities import evaluate, normalize

NOW = datetime(2026, 8, 13, 15, 0, tzinfo=timezone.utc)


class OpportunityDecisionV2Tests(unittest.TestCase):
    def base(self):
        return {
            "source_platform": "test",
            "campaign_id": "c1",
            "title": "Valid campaign",
            "category": "clipping",
            "usage_rights": "Verified campaign licence for intended publication",
            "expected_revenue": 100,
            "estimated_success_probability": 0.5,
            "probability_collection": 0.8,
            "expected_production_cost": 5,
            "expected_laptop_minutes": 30,
            "expected_owner_minutes": 0,
            "rights_verification_state": "VERIFIED",
            "compliance_risk": "LOW",
            "platform_risk": "LOW",
            "duplicate_conflict_status": "CLEAR",
            "user_attention_requirement": "NONE",
            "source_checked_at": (NOW - timedelta(minutes=5)).isoformat(),
            "freshness_ttl_seconds": 3600,
            "deadline": "2026-08-20T12:00:00+00:00",
            "remaining_budget": 1000,
            "payout_formula": "EUR 1 per qualified unit",
        }

    def test_normalizes_collectible_profit_without_false_cash_claim(self):
        op = normalize(self.base(), now=NOW)
        self.assertEqual(op["expected_collectible_revenue"], 40.0)
        self.assertEqual(op["expected_net_profit"], 35.0)
        self.assertEqual(op["expected_profit_per_laptop_hour"], 70.0)

    def test_unknown_rights_reject_fail_closed(self):
        raw = self.base()
        raw["rights_verification_state"] = "CLAIMED_UNVERIFIED"
        decision = evaluate(normalize(raw, now=NOW), now=NOW)
        self.assertEqual(decision.decision, "REJECT")
        self.assertEqual(decision.decision_reasons, ("RIGHTS_NOT_VERIFIED",))
        self.assertFalse(decision.eligible_for_queue)

    def test_stale_source_revalidates_instead_of_rejecting(self):
        raw = self.base()
        raw["source_checked_at"] = (NOW - timedelta(hours=2)).isoformat()
        raw["freshness_ttl_seconds"] = 3600
        decision = evaluate(normalize(raw, now=NOW), now=NOW)
        self.assertEqual(decision.decision, "REVALIDATE")
        self.assertTrue(decision.requires_revalidation)
        self.assertIn("source_checked_at", decision.revalidation_fields)

    def test_missing_volatile_payout_data_revalidates(self):
        raw = self.base()
        raw["remaining_budget"] = None
        decision = evaluate(normalize(raw, now=NOW), now=NOW)
        self.assertEqual(decision.decision, "REVALIDATE")
        self.assertIn("remaining_budget", decision.revalidation_fields)

    def test_kyc_is_pause_not_routine_operator_assignment(self):
        raw = self.base()
        raw["user_attention_requirement"] = "KYC"
        decision = evaluate(normalize(raw, now=NOW), now=NOW)
        self.assertEqual(decision.decision, "PAUSE")
        self.assertFalse(decision.eligible_for_queue)

    def test_recurring_owner_work_is_rejected(self):
        raw = self.base()
        raw["expected_owner_minutes"] = 1
        decision = evaluate(normalize(raw, now=NOW), now=NOW)
        self.assertEqual(decision.decision, "REJECT")
        self.assertEqual(decision.decision_reasons, ("RECURRING_OWNER_WORK_REQUIRED",))

    def test_negative_margin_rejects_when_fresh(self):
        raw = self.base()
        raw["expected_production_cost"] = 50
        decision = evaluate(normalize(raw, now=NOW), now=NOW)
        self.assertEqual(decision.decision, "REJECT")
        self.assertEqual(decision.decision_reasons, ("NON_POSITIVE_EXPECTED_MARGIN",))

    def test_duplicate_conflict_pauses(self):
        raw = self.base()
        raw["duplicate_conflict_status"] = "CONFLICT"
        decision = evaluate(normalize(raw, now=NOW), now=NOW)
        self.assertEqual(decision.decision, "PAUSE")

    def test_valid_hard_gates_still_revalidate_until_scoring_is_versioned(self):
        decision = evaluate(normalize(self.base(), now=NOW), now=NOW)
        self.assertEqual(decision.decision, "REVALIDATE")
        self.assertEqual(decision.revalidation_fields, ("priority_score",))
        payload = decision.to_dict()
        self.assertEqual(payload["policy_version"], "opportunity-decision-policy/1")
        self.assertFalse(payload["eligible_for_queue"])


if __name__ == "__main__":
    unittest.main()
