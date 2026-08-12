import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.opportunities import evaluate, normalize


class OpportunityTests(unittest.TestCase):
    def base(self):
        return {
            "source_platform": "test",
            "campaign_id": "c1",
            "title": "Valid campaign",
            "category": "clipping",
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
        }

    def test_calculates_collectible_profit(self):
        op = normalize(self.base())
        self.assertEqual(op["expected_collectible_revenue"], 40.0)
        self.assertEqual(op["expected_net_profit"], 35.0)
        self.assertEqual(op["expected_profit_per_laptop_hour"], 70.0)
        self.assertTrue(evaluate(op).accepted)

    def test_rejects_unverified_rights(self):
        raw = self.base()
        raw["rights_verification_state"] = "CLAIMED_UNVERIFIED"
        decision = evaluate(normalize(raw))
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "RIGHTS_NOT_VERIFIED")

    def test_rejects_negative_margin(self):
        raw = self.base()
        raw["expected_production_cost"] = 50
        decision = evaluate(normalize(raw))
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "NON_POSITIVE_EXPECTED_MARGIN")

    def test_rejects_recurring_owner_work(self):
        raw = self.base()
        raw["expected_owner_minutes"] = 1
        decision = evaluate(normalize(raw))
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "RECURRING_OWNER_WORK_REQUIRED")

    def test_raw_input_can_be_incomplete_but_fails_closed(self):
        op = normalize({"source_platform": "adapter", "title": "Sparse"})
        self.assertEqual(op["status"], "DISCOVERED")
        self.assertFalse(evaluate(op).accepted)


if __name__ == "__main__":
    unittest.main()
