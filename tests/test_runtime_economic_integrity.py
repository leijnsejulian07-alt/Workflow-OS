import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.opportunities import evaluate, normalize

NOW = datetime(2026, 8, 18, 9, 0, tzinfo=timezone.utc)


class RuntimeEconomicIntegrityTests(unittest.TestCase):
    def accepted_opportunity(self):
        raw = {
            "source_platform": "test",
            "campaign_id": "runtime-economics",
            "title": "Runtime economics fixture",
            "category": "clipping",
            "usage_rights": "Verified campaign licence for intended publication",
            "expected_revenue": 100,
            "estimated_success_probability": 0.5,
            "probability_collection": 0.8,
            "expected_production_cost": 5,
            "expected_laptop_minutes": 30,
            "expected_owner_minutes": 0,
            "expected_time_to_cash_hours": 48,
            "automation_completeness": 1.0,
            "capital_required": 0,
            "rights_verification_state": "VERIFIED",
            "compliance_risk": "LOW",
            "platform_risk": "LOW",
            "duplicate_conflict_status": "CLEAR",
            "user_attention_requirement": "NONE",
            "source_checked_at": (NOW - timedelta(minutes=5)).isoformat(),
            "freshness_ttl_seconds": 3600,
            "deadline": (NOW + timedelta(days=2)).isoformat(),
            "remaining_budget": 1000,
            "payout_formula": "EUR 1 per qualified unit",
            "payout_cap": 1000,
            "payment_method": "Platform payout after approval",
            "approval_rules": "Qualified unit must pass platform review",
            "originality_requirements": "Original compliant production required",
            "account_requirements": [],
        }
        op = normalize(raw, now=NOW)
        self.assertEqual(evaluate(op, now=NOW).decision, "ACCEPT")
        return op

    def assert_runtime_revalidates(self, field, value):
        op = self.accepted_opportunity()
        op[field] = value
        decision = evaluate(op, now=NOW)
        self.assertEqual(decision.decision, "REVALIDATE")
        self.assertFalse(decision.eligible_for_queue)
        self.assertIn(field, decision.revalidation_fields)

    def test_nonnegative_amounts_fail_closed_when_direct_evaluate_bypasses_normalize(self):
        fields = (
            "expected_revenue",
            "expected_production_cost",
            "expected_laptop_minutes",
            "expected_collectible_revenue",
        )
        invalid_values = (-0.01, "unknown", float("nan"), float("inf"), float("-inf"), None)
        for field in fields:
            for value in invalid_values:
                with self.subTest(field=field, value=value):
                    self.assert_runtime_revalidates(field, value)

    def test_probability_evidence_is_revalidated_outside_closed_unit_interval(self):
        for field in ("estimated_success_probability", "probability_collection"):
            for value in (-0.01, 1.01, "unknown", float("nan"), float("inf"), float("-inf"), None):
                with self.subTest(field=field, value=value):
                    self.assert_runtime_revalidates(field, value)

    def test_derived_profit_evidence_requires_finite_numbers(self):
        for field in ("expected_net_profit", "expected_profit_per_laptop_hour"):
            for value in ("unknown", float("nan"), float("inf"), float("-inf"), None):
                with self.subTest(field=field, value=value):
                    self.assert_runtime_revalidates(field, value)

    def test_known_non_positive_margin_keeps_existing_hard_rejection(self):
        op = self.accepted_opportunity()
        op["expected_net_profit"] = 0
        decision = evaluate(op, now=NOW)
        self.assertEqual(decision.decision, "REJECT")
        self.assertEqual(decision.decision_reasons, ("NON_POSITIVE_EXPECTED_MARGIN",))

    def test_known_non_positive_laptop_profit_keeps_existing_hard_rejection(self):
        op = self.accepted_opportunity()
        op["expected_profit_per_laptop_hour"] = 0
        decision = evaluate(op, now=NOW)
        self.assertEqual(decision.decision, "REJECT")
        self.assertEqual(decision.decision_reasons, ("NON_POSITIVE_LAPTOP_HOUR_PROFIT",))

    def test_zero_production_cost_remains_valid_evidence(self):
        op = self.accepted_opportunity()
        op["expected_production_cost"] = 0
        self.assertEqual(evaluate(op, now=NOW).decision, "ACCEPT")


if __name__ == "__main__":
    unittest.main()
