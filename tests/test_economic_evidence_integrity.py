import math
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.opportunities import evaluate, normalize

NOW = datetime(2026, 8, 16, 2, 0, tzinfo=timezone.utc)


class EconomicEvidenceIntegrityTests(unittest.TestCase):
    def base(self):
        return {
            "source_platform": "test",
            "campaign_id": "economic-integrity",
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
            "payment_method": "Platform payout after approval",
            "approval_rules": "Qualified deliverables are reviewed under the campaign rules",
            "originality_requirements": "Original compliant edit required",
            "account_requirements": [],
        }

    def assert_revalidates_field(self, field, value):
        raw = self.base()
        raw[field] = value
        op = normalize(raw, now=NOW)
        self.assertIsNone(op[field], f"{field} should remain unknown for {value!r}")
        decision = evaluate(op, now=NOW)
        self.assertEqual(decision.decision, "REVALIDATE")
        self.assertIn(field, decision.revalidation_fields)
        self.assertFalse(decision.eligible_for_queue)

    def test_invalid_primary_economic_evidence_is_not_clamped(self):
        fields = ("expected_revenue", "expected_production_cost", "expected_laptop_minutes")
        invalid_values = (-0.01, "not-a-number", math.nan, math.inf, -math.inf)
        for field in fields:
            for value in invalid_values:
                with self.subTest(field=field, value=value):
                    self.assert_revalidates_field(field, value)

    def test_missing_primary_economic_evidence_revalidates(self):
        for field in ("expected_revenue", "expected_production_cost", "expected_laptop_minutes"):
            with self.subTest(field=field):
                raw = self.base()
                raw.pop(field)
                op = normalize(raw, now=NOW)
                self.assertIsNone(op[field])
                decision = evaluate(op, now=NOW)
                self.assertEqual(decision.decision, "REVALIDATE")
                self.assertIn(field, decision.revalidation_fields)

    def test_invalid_supplied_collectible_revenue_is_not_clamped(self):
        for value in (-1, "unknown", math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                self.assert_revalidates_field("expected_collectible_revenue", value)

    def test_absent_collectible_revenue_is_derived_only_from_known_inputs(self):
        op = normalize(self.base(), now=NOW)
        self.assertEqual(op["expected_collectible_revenue"], 40.0)
        self.assertEqual(op["expected_net_profit"], 35.0)

        raw = self.base()
        raw["expected_revenue"] = "unknown"
        op = normalize(raw, now=NOW)
        self.assertIsNone(op["expected_collectible_revenue"])
        self.assertIsNone(op["expected_net_profit"])

    def test_explicit_zero_is_preserved_as_valid_syntax(self):
        raw = self.base()
        raw["expected_revenue"] = 0
        op = normalize(raw, now=NOW)
        self.assertEqual(op["expected_revenue"], 0.0)
        self.assertEqual(op["expected_collectible_revenue"], 0.0)
        decision = evaluate(op, now=NOW)
        self.assertEqual(decision.decision, "REJECT")
        self.assertEqual(decision.decision_reasons, ("COLLECTIBLE_REVENUE_UNSUPPORTED",))

        raw = self.base()
        raw["expected_production_cost"] = 0
        raw["expected_laptop_minutes"] = 0
        op = normalize(raw, now=NOW)
        self.assertEqual(op["expected_production_cost"], 0.0)
        self.assertEqual(op["expected_laptop_minutes"], 0.0)
        self.assertEqual(evaluate(op, now=NOW).decision, "ACCEPT")


if __name__ == "__main__":
    unittest.main()
