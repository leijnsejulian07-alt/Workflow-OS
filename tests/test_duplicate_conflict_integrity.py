import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.opportunities import evaluate, normalize

NOW = datetime(2026, 8, 16, 20, 0, tzinfo=timezone.utc)


class DuplicateConflictIntegrityTests(unittest.TestCase):
    def base(self):
        return {
            "source_platform": "test",
            "campaign_id": "duplicate-integrity",
            "title": "Verified opportunity",
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
            "deadline": "2026-08-20T12:00:00+00:00",
            "remaining_budget": 1000,
            "payout_formula": "EUR 1 per qualified unit",
            "payout_cap": 1000,
            "payment_method": "platform payout",
            "approval_rules": "Platform approval after qualified delivery",
            "originality_requirements": "Original compliant output required",
            "account_requirements": [],
        }

    def assert_revalidates_duplicate_evidence(self, raw):
        op = normalize(raw, now=NOW)
        decision = evaluate(op, now=NOW)
        self.assertEqual(decision.decision, "REVALIDATE")
        self.assertTrue(decision.requires_revalidation)
        self.assertIn("duplicate_conflict_status", decision.revalidation_fields)
        self.assertFalse(decision.eligible_for_queue)

    def test_missing_duplicate_status_revalidates(self):
        raw = self.base()
        raw.pop("duplicate_conflict_status")
        self.assert_revalidates_duplicate_evidence(raw)

    def test_invalid_duplicate_statuses_revalidate(self):
        for value in (None, "", "UNKNOWN", "not-a-state", 0, False, [], {}):
            with self.subTest(value=value):
                raw = self.base()
                raw["duplicate_conflict_status"] = value
                self.assert_revalidates_duplicate_evidence(raw)

    def test_clear_status_can_accept(self):
        raw = self.base()
        raw["duplicate_conflict_status"] = "CLEAR"
        decision = evaluate(normalize(raw, now=NOW), now=NOW)
        self.assertEqual(decision.decision, "ACCEPT")
        self.assertTrue(decision.eligible_for_queue)

    def test_duplicate_and_conflict_pause(self):
        for value in ("DUPLICATE", "CONFLICT"):
            with self.subTest(value=value):
                raw = self.base()
                raw["duplicate_conflict_status"] = value
                decision = evaluate(normalize(raw, now=NOW), now=NOW)
                self.assertEqual(decision.decision, "PAUSE")
                self.assertEqual(decision.decision_reasons, ("DUPLICATE_OR_CONFLICT",))
                self.assertFalse(decision.eligible_for_queue)


if __name__ == "__main__":
    unittest.main()
