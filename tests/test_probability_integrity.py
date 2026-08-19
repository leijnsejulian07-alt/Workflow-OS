import math
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.opportunities import evaluate, normalize

NOW = datetime(2026, 8, 16, 0, 0, tzinfo=timezone.utc)


class ProbabilityIntegrityTests(unittest.TestCase):
    def base(self):
        return {
            "source_platform": "test",
            "campaign_id": "probability-integrity",
            "title": "Probability integrity fixture",
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
            "deadline": (NOW + timedelta(days=7)).isoformat(),
            "remaining_budget": 1000,
            "payout_formula": "EUR 1 per qualified unit",
            "payout_cap": 1000,
            "payment_method": "Platform payout to verified account",
            "approval_rules": "Qualified submissions require platform approval",
            "originality_requirements": "Original compliant edit required",
            "account_requirements": ["Verified platform account"],
        }

    def assert_revalidates_probability(self, field, value):
        raw = self.base()
        raw[field] = value
        op = normalize(raw, now=NOW)
        decision = evaluate(op, now=NOW)
        self.assertIsNone(op[field])
        self.assertEqual(decision.decision, "REVALIDATE")
        self.assertIn(field, decision.revalidation_fields)
        self.assertFalse(decision.eligible_for_queue)

    def test_out_of_range_probabilities_fail_closed(self):
        for field in ("estimated_success_probability", "probability_collection"):
            for value in (-0.01, 1.01):
                with self.subTest(field=field, value=value):
                    self.assert_revalidates_probability(field, value)

    def test_non_finite_probabilities_fail_closed(self):
        for field in ("estimated_success_probability", "probability_collection"):
            for value in (math.nan, math.inf, -math.inf, "NaN", "Infinity"):
                with self.subTest(field=field, value=value):
                    self.assert_revalidates_probability(field, value)

    def test_malformed_probabilities_fail_closed(self):
        for field in ("estimated_success_probability", "probability_collection"):
            with self.subTest(field=field):
                self.assert_revalidates_probability(field, "not-a-probability")

    def test_probability_boundaries_are_valid_evidence(self):
        for field in ("estimated_success_probability", "probability_collection"):
            for value in (0, 1):
                raw = self.base()
                raw[field] = value
                op = normalize(raw, now=NOW)
                with self.subTest(field=field, value=value):
                    self.assertEqual(op[field], float(value))
                    decision = evaluate(op, now=NOW)
                    self.assertNotIn(field, decision.revalidation_fields)


if __name__ == "__main__":
    unittest.main()
