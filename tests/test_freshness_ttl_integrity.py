import math
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.opportunities import evaluate, normalize

NOW = datetime(2026, 8, 16, 9, 0, tzinfo=timezone.utc)


class FreshnessTtlIntegrityTests(unittest.TestCase):
    def base(self):
        return {
            "source_platform": "test",
            "campaign_id": "ttl-integrity",
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
            "payment_method": "Platform payout",
            "approval_rules": "Qualified units require platform approval",
            "originality_requirements": "Original compliant production required",
            "account_requirements": [],
        }

    def assert_revalidates(self, value):
        raw = self.base()
        raw["freshness_ttl_seconds"] = value
        op = normalize(raw, now=NOW)
        self.assertIsNone(op["freshness_ttl_seconds"])
        decision = evaluate(op, now=NOW)
        self.assertEqual(decision.decision, "REVALIDATE")
        self.assertIn("freshness_ttl_seconds", decision.revalidation_fields)
        self.assertFalse(decision.eligible_for_queue)
        self.assertIsNone(decision.freshness_expires_at)

    def test_invalid_ttl_is_not_clamped_or_defaulted(self):
        for value in (-1, "unknown", math.nan, math.inf, -math.inf, 1.5):
            with self.subTest(value=value):
                self.assert_revalidates(value)

    def test_missing_or_null_ttl_revalidates(self):
        raw = self.base()
        raw.pop("freshness_ttl_seconds")
        op = normalize(raw, now=NOW)
        self.assertIsNone(op["freshness_ttl_seconds"])
        decision = evaluate(op, now=NOW)
        self.assertEqual(decision.decision, "REVALIDATE")
        self.assertIn("freshness_ttl_seconds", decision.revalidation_fields)
        self.assertIsNone(decision.freshness_expires_at)
        self.assert_revalidates(None)

    def test_explicit_zero_is_preserved_but_not_queue_eligible(self):
        raw = self.base()
        raw["freshness_ttl_seconds"] = 0
        op = normalize(raw, now=NOW)
        self.assertEqual(op["freshness_ttl_seconds"], 0)
        decision = evaluate(op, now=NOW)
        self.assertEqual(decision.decision, "REVALIDATE")
        self.assertFalse(decision.eligible_for_queue)

    def test_positive_integer_ttl_keeps_exact_expiry_and_accepts(self):
        raw = self.base()
        raw["freshness_ttl_seconds"] = 3600
        op = normalize(raw, now=NOW)
        self.assertEqual(op["freshness_ttl_seconds"], 3600)
        decision = evaluate(op, now=NOW)
        self.assertEqual(decision.decision, "ACCEPT")
        checked = datetime.fromisoformat(raw["source_checked_at"])
        self.assertEqual(decision.freshness_expires_at, (checked + timedelta(seconds=3600)).isoformat())


if __name__ == "__main__":
    unittest.main()
