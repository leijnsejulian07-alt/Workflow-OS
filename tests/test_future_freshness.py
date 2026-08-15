import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.opportunities import evaluate, normalize

NOW = datetime(2026, 8, 15, 4, 0, tzinfo=timezone.utc)


class FutureFreshnessTests(unittest.TestCase):
    def valid_opportunity(self):
        return {
            "source_platform": "test",
            "campaign_id": "future-freshness",
            "title": "Future freshness regression",
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
            "freshness_ttl_seconds": 3600,
            "deadline": "2026-08-20T12:00:00+00:00",
            "remaining_budget": 1000,
            "payout_formula": "EUR 1 per qualified unit",
        }

    def test_future_source_checks_require_revalidation(self):
        for offset in (timedelta(minutes=1), timedelta(days=30)):
            with self.subTest(offset=offset):
                raw = self.valid_opportunity()
                raw["source_checked_at"] = (NOW + offset).isoformat()
                decision = evaluate(normalize(raw, now=NOW), now=NOW)
                self.assertEqual(decision.decision, "REVALIDATE")
                self.assertIn("source_checked_at", decision.revalidation_fields)
                self.assertFalse(decision.eligible_for_queue)


if __name__ == "__main__":
    unittest.main()
