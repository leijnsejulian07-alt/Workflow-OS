import math
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.opportunities import evaluate, normalize

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


class RuntimeRemainingBudgetIntegrityTests(unittest.TestCase):
    def normalized_base(self):
        raw = {
            "source_platform": "test",
            "campaign_id": "runtime-budget-integrity",
            "title": "Known profitable opportunity",
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
            "payment_method": "Platform payout to verified account",
            "approval_rules": "Qualified units require platform approval",
            "originality_requirements": "Original compliant production required",
            "account_requirements": [],
        }
        return normalize(raw, now=NOW)

    def assert_direct_evaluate_revalidates(self, value):
        op = self.normalized_base()
        op["remaining_budget"] = value
        decision = evaluate(op, now=NOW)
        self.assertEqual(decision.decision, "REVALIDATE")
        self.assertIn("remaining_budget", decision.revalidation_fields)
        self.assertFalse(decision.eligible_for_queue)

    def test_direct_evaluate_rejects_invalid_budget_evidence(self):
        for value in (-0.01, "unknown", math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                self.assert_direct_evaluate_revalidates(value)

    def test_direct_evaluate_rejects_missing_or_null_budget_evidence(self):
        op = self.normalized_base()
        op.pop("remaining_budget")
        decision = evaluate(op, now=NOW)
        self.assertEqual(decision.decision, "REVALIDATE")
        self.assertIn("remaining_budget", decision.revalidation_fields)
        self.assertFalse(decision.eligible_for_queue)
        self.assert_direct_evaluate_revalidates(None)

    def test_direct_evaluate_accepts_explicit_zero_and_positive_finite_budget(self):
        for value in (0, 1000.25):
            with self.subTest(value=value):
                op = self.normalized_base()
                op["remaining_budget"] = value
                self.assertEqual(evaluate(op, now=NOW).decision, "ACCEPT")


if __name__ == "__main__":
    unittest.main()
