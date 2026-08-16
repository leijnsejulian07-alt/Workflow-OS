import math
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.opportunities import evaluate, normalize

NOW = datetime(2026, 8, 16, 5, 0, tzinfo=timezone.utc)


class RemainingBudgetIntegrityTests(unittest.TestCase):
    def base(self):
        return {
            "source_platform": "test",
            "campaign_id": "budget-integrity",
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
        }

    def assert_revalidates(self, value):
        raw = self.base()
        raw["remaining_budget"] = value
        op = normalize(raw, now=NOW)
        self.assertIsNone(op["remaining_budget"])
        decision = evaluate(op, now=NOW)
        self.assertEqual(decision.decision, "REVALIDATE")
        self.assertIn("remaining_budget", decision.revalidation_fields)
        self.assertFalse(decision.eligible_for_queue)

    def test_invalid_remaining_budget_is_not_clamped_or_trusted(self):
        for value in (-0.01, "unknown", math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                self.assert_revalidates(value)

    def test_missing_or_null_remaining_budget_revalidates(self):
        raw = self.base()
        raw.pop("remaining_budget")
        op = normalize(raw, now=NOW)
        self.assertIsNone(op["remaining_budget"])
        self.assertEqual(evaluate(op, now=NOW).decision, "REVALIDATE")

        self.assert_revalidates(None)

    def test_zero_and_positive_finite_budget_are_valid_evidence(self):
        for value in (0, 1000.25):
            with self.subTest(value=value):
                raw = self.base()
                raw["remaining_budget"] = value
                op = normalize(raw, now=NOW)
                self.assertEqual(op["remaining_budget"], float(value))
                self.assertEqual(evaluate(op, now=NOW).decision, "ACCEPT")


if __name__ == "__main__":
    unittest.main()
