import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.opportunities import evaluate, normalize

NOW = datetime(2026, 8, 17, 1, 0, tzinfo=timezone.utc)


class OwnerAttentionIntegrityTests(unittest.TestCase):
    def base(self):
        return {
            "source_platform": "test",
            "campaign_id": "attention-1",
            "title": "Valid zero-touch campaign",
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
        }

    def assert_revalidates_attention(self, raw):
        op = normalize(raw, now=NOW)
        self.assertIsNone(op["user_attention_requirement"])
        decision = evaluate(op, now=NOW)
        self.assertEqual(decision.decision, "REVALIDATE")
        self.assertTrue(decision.requires_revalidation)
        self.assertIn("user_attention_requirement", decision.revalidation_fields)
        self.assertFalse(decision.eligible_for_queue)
        self.assertNotEqual(decision.owner_attention_requirement, "NONE")

    def test_missing_attention_does_not_become_none(self):
        raw = self.base()
        raw.pop("user_attention_requirement")
        self.assert_revalidates_attention(raw)

    def test_invalid_attention_evidence_revalidates(self):
        for value in (None, "", "   ", "operator", 0, 1, False, True, [], {}, ["NONE"]):
            with self.subTest(value=value):
                raw = self.base()
                raw["user_attention_requirement"] = value
                self.assert_revalidates_attention(raw)

    def test_explicit_none_remains_valid_zero_touch_evidence(self):
        raw = self.base()
        raw["user_attention_requirement"] = " none "
        op = normalize(raw, now=NOW)
        self.assertEqual(op["user_attention_requirement"], "NONE")
        decision = evaluate(op, now=NOW)
        self.assertEqual(decision.decision, "ACCEPT")
        self.assertTrue(decision.eligible_for_queue)

    def test_allowed_owner_interventions_pause(self):
        for state in ("OWNER_APPROVAL", "KYC", "EXCEPTION", "EMERGENCY"):
            with self.subTest(state=state):
                raw = self.base()
                raw["user_attention_requirement"] = state
                decision = evaluate(normalize(raw, now=NOW), now=NOW)
                self.assertEqual(decision.decision, "PAUSE")
                self.assertFalse(decision.eligible_for_queue)
                self.assertEqual(decision.owner_attention_requirement, state)


if __name__ == "__main__":
    unittest.main()
