import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.opportunities import evaluate, normalize

NOW = datetime(2026, 8, 15, 18, 0, tzinfo=timezone.utc)


class DeadlineExpiryTests(unittest.TestCase):
    def base(self):
        return {
            "source_platform": "test",
            "campaign_id": "deadline-gate",
            "title": "Deadline boundary campaign",
            "category": "clipping",
            "usage_rights": "Verified campaign licence for intended publication",
            "expected_revenue": 100,
            "estimated_success_probability": 0.5,
            "probability_collection": 0.8,
            "expected_production_cost": 5,
            "expected_laptop_minutes": 30,
            "expected_owner_minutes": 0,
            "expected_time_to_cash_hours": 24,
            "automation_completeness": 1.0,
            "capital_required": 0,
            "rights_verification_state": "VERIFIED",
            "compliance_risk": "LOW",
            "platform_risk": "LOW",
            "duplicate_conflict_status": "CLEAR",
            "user_attention_requirement": "NONE",
            "source_checked_at": (NOW - timedelta(minutes=5)).isoformat(),
            "freshness_ttl_seconds": 3600,
            "deadline": (NOW + timedelta(days=1)).isoformat(),
            "remaining_budget": 1000,
            "payout_formula": "EUR 1 per qualified unit",
        }

    def decision(self, deadline):
        raw = self.base()
        raw["deadline"] = deadline
        return evaluate(normalize(raw, now=NOW), now=NOW)

    def test_past_deadline_rejects(self):
        decision = self.decision((NOW - timedelta(seconds=1)).isoformat())
        self.assertEqual(decision.decision, "REJECT")
        self.assertEqual(decision.decision_reasons, ("DEADLINE_EXPIRED",))
        self.assertFalse(decision.eligible_for_queue)

    def test_deadline_equal_now_rejects(self):
        decision = self.decision(NOW.isoformat())
        self.assertEqual(decision.decision, "REJECT")
        self.assertEqual(decision.decision_reasons, ("DEADLINE_EXPIRED",))
        self.assertFalse(decision.eligible_for_queue)

    def test_malformed_deadline_revalidates(self):
        decision = self.decision("not-a-date")
        self.assertEqual(decision.decision, "REVALIDATE")
        self.assertIn("deadline", decision.revalidation_fields)
        self.assertFalse(decision.eligible_for_queue)

    def test_future_deadline_preserves_accept(self):
        decision = self.decision((NOW + timedelta(minutes=1)).isoformat())
        self.assertEqual(decision.decision, "ACCEPT")
        self.assertTrue(decision.eligible_for_queue)


if __name__ == "__main__":
    unittest.main()
