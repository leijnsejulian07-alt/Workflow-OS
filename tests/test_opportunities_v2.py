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
            "source_platform": "test", "campaign_id": "c1", "title": "Valid campaign", "category": "clipping",
            "usage_rights": "Verified campaign licence for intended publication", "expected_revenue": 100,
            "estimated_success_probability": 0.5, "probability_collection": 0.8, "expected_production_cost": 5,
            "expected_laptop_minutes": 30, "expected_owner_minutes": 0, "expected_time_to_cash_hours": 48,
            "automation_completeness": 1.0, "capital_required": 0, "rights_verification_state": "VERIFIED",
            "compliance_risk": "LOW", "platform_risk": "LOW", "duplicate_conflict_status": "CLEAR",
            "user_attention_requirement": "NONE", "source_checked_at": (NOW - timedelta(minutes=5)).isoformat(),
            "freshness_ttl_seconds": 3600, "deadline": "2026-08-20T12:00:00+00:00", "remaining_budget": 1000,
            "payout_formula": "EUR 1 per qualified unit", "payout_cap": 1000,
            "payment_method": "Platform payout after approved qualified units",
            "approval_rules": "Platform reviews submitted units against campaign requirements",
            "originality_requirements": "Original compliant production using only licensed source assets",
            "account_requirements": [],
        }

    def test_normalizes_collectible_profit_without_false_cash_claim(self):
        op = normalize(self.base(), now=NOW)
        self.assertEqual(op["expected_collectible_revenue"], 40.0)
        self.assertEqual(op["expected_net_profit"], 35.0)
        self.assertEqual(op["expected_profit_per_laptop_hour"], 70.0)

    def test_unknown_collection_probability_revalidates(self):
        raw = self.base(); raw.pop("probability_collection")
        decision = evaluate(normalize(raw, now=NOW), now=NOW)
        self.assertEqual(decision.decision, "REVALIDATE"); self.assertIn("probability_collection", decision.revalidation_fields)

    def test_missing_source_check_does_not_become_fresh_now(self):
        raw = self.base(); raw.pop("source_checked_at")
        decision = evaluate(normalize(raw, now=NOW), now=NOW)
        self.assertEqual(decision.decision, "REVALIDATE"); self.assertIn("source_checked_at", decision.revalidation_fields)

    def test_unknown_rights_reject_fail_closed(self):
        raw = self.base(); raw["rights_verification_state"] = "CLAIMED_UNVERIFIED"
        decision = evaluate(normalize(raw, now=NOW), now=NOW)
        self.assertEqual(decision.decision, "REJECT"); self.assertEqual(decision.decision_reasons, ("RIGHTS_NOT_VERIFIED",)); self.assertFalse(decision.eligible_for_queue)

    def test_stale_source_revalidates_instead_of_rejecting(self):
        raw = self.base(); raw["source_checked_at"] = (NOW - timedelta(hours=2)).isoformat()
        decision = evaluate(normalize(raw, now=NOW), now=NOW)
        self.assertEqual(decision.decision, "REVALIDATE"); self.assertIn("source_checked_at", decision.revalidation_fields)

    def test_missing_volatile_payout_data_revalidates(self):
        raw = self.base(); raw["remaining_budget"] = None
        decision = evaluate(normalize(raw, now=NOW), now=NOW)
        self.assertEqual(decision.decision, "REVALIDATE"); self.assertIn("remaining_budget", decision.revalidation_fields)

    def test_kyc_is_pause_not_routine_operator_assignment(self):
        raw = self.base(); raw["user_attention_requirement"] = "KYC"
        decision = evaluate(normalize(raw, now=NOW), now=NOW)
        self.assertEqual(decision.decision, "PAUSE"); self.assertFalse(decision.eligible_for_queue)

    def test_missing_owner_workload_revalidates(self):
        raw = self.base(); raw.pop("expected_owner_minutes")
        op = normalize(raw, now=NOW); self.assertIsNone(op["expected_owner_minutes"])
        decision = evaluate(op, now=NOW)
        self.assertEqual(decision.decision, "REVALIDATE"); self.assertIn("expected_owner_minutes", decision.revalidation_fields); self.assertFalse(decision.eligible_for_queue)

    def test_invalid_owner_workload_evidence_never_becomes_zero(self):
        for value in (None, "unknown", -5, float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                raw = self.base(); raw["expected_owner_minutes"] = value
                op = normalize(raw, now=NOW)
                self.assertIsNone(op["expected_owner_minutes"])
                decision = evaluate(op, now=NOW)
                self.assertEqual(decision.decision, "REVALIDATE")
                self.assertIn("expected_owner_minutes", decision.revalidation_fields)
                self.assertFalse(decision.eligible_for_queue)

    def test_explicit_zero_owner_workload_can_accept(self):
        raw = self.base(); raw["expected_owner_minutes"] = 0
        decision = evaluate(normalize(raw, now=NOW), now=NOW)
        self.assertEqual(decision.decision, "ACCEPT"); self.assertTrue(decision.eligible_for_queue)

    def test_recurring_owner_work_is_rejected(self):
        raw = self.base(); raw["expected_owner_minutes"] = 1
        decision = evaluate(normalize(raw, now=NOW), now=NOW)
        self.assertEqual(decision.decision, "REJECT"); self.assertEqual(decision.decision_reasons, ("RECURRING_OWNER_WORK_REQUIRED",))

    def test_negative_margin_rejects_when_fresh(self):
        raw = self.base(); raw["expected_production_cost"] = 50
        decision = evaluate(normalize(raw, now=NOW), now=NOW)
        self.assertEqual(decision.decision, "REJECT"); self.assertEqual(decision.decision_reasons, ("NON_POSITIVE_EXPECTED_MARGIN",))

    def test_duplicate_conflict_pauses(self):
        raw = self.base(); raw["duplicate_conflict_status"] = "CONFLICT"
        self.assertEqual(evaluate(normalize(raw, now=NOW), now=NOW).decision, "PAUSE")

    def test_valid_known_inputs_accept_and_queue(self):
        decision = evaluate(normalize(self.base(), now=NOW), now=NOW)
        self.assertEqual(decision.decision, "ACCEPT"); self.assertTrue(decision.eligible_for_queue); self.assertGreater(decision.priority_score, 0)

    def test_unknown_priority_input_revalidates(self):
        raw = self.base(); raw.pop("expected_time_to_cash_hours")
        decision = evaluate(normalize(raw, now=NOW), now=NOW)
        self.assertEqual(decision.decision, "REVALIDATE"); self.assertIn("expected_time_to_cash_hours", decision.revalidation_fields)

    def test_priority_score_is_deterministic(self):
        op = normalize(self.base(), now=NOW); self.assertEqual(evaluate(op, now=NOW).priority_score, evaluate(op, now=NOW).priority_score)

    def test_better_economics_raise_priority(self):
        base = self.base(); better = self.base(); better["expected_revenue"] = 200
        self.assertGreater(evaluate(normalize(better, now=NOW), now=NOW).priority_score, evaluate(normalize(base, now=NOW), now=NOW).priority_score)

    def test_faster_time_to_cash_raises_priority(self):
        slow = self.base(); fast = self.base(); slow["expected_time_to_cash_hours"] = 168; fast["expected_time_to_cash_hours"] = 12
        self.assertGreater(evaluate(normalize(fast, now=NOW), now=NOW).priority_score, evaluate(normalize(slow, now=NOW), now=NOW).priority_score)


if __name__ == "__main__":
    unittest.main()
