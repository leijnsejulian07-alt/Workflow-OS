import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.opportunities import evaluate, normalize

NOW = datetime(2026, 8, 16, 17, 0, tzinfo=timezone.utc)


def base():
    return {
        "source_platform": "test", "campaign_id": "risk-1", "title": "Risk evidence", "category": "clipping",
        "usage_rights": "Verified campaign licence", "rights_verification_state": "VERIFIED",
        "expected_revenue": 100, "estimated_success_probability": 0.5, "probability_collection": 0.8,
        "expected_production_cost": 5, "expected_laptop_minutes": 30, "expected_owner_minutes": 0,
        "expected_time_to_cash_hours": 24, "automation_completeness": 1.0, "capital_required": 0,
        "compliance_risk": "LOW", "platform_risk": "LOW", "duplicate_conflict_status": "CLEAR",
        "user_attention_requirement": "NONE", "source_checked_at": (NOW - timedelta(minutes=5)).isoformat(),
        "freshness_ttl_seconds": 3600, "deadline": (NOW + timedelta(days=2)).isoformat(),
        "remaining_budget": 1000, "payout_formula": "EUR 1 per qualified unit",
        "payout_cap": 1000, "payment_method": "platform payout",
        "approval_rules": "Qualified units require platform approval",
        "originality_requirements": "Original compliant edit required",
        "account_requirements": [],
    }


class RiskEvidenceIntegrityTests(unittest.TestCase):
    def test_invalid_risk_evidence_revalidates(self):
        invalid_values = (None, "", "unknown", "critical", 1, [], {})
        for field in ("compliance_risk", "platform_risk"):
            for value in invalid_values:
                with self.subTest(field=field, value=value):
                    raw = base(); raw[field] = value
                    op = normalize(raw, now=NOW)
                    self.assertIsNone(op[field])
                    decision = evaluate(op, now=NOW)
                    self.assertEqual(decision.decision, "REVALIDATE")
                    self.assertIn(field, decision.revalidation_fields)
                    self.assertFalse(decision.eligible_for_queue)
                    self.assertEqual(decision.priority_score, 0.0)

    def test_missing_risk_evidence_revalidates(self):
        for field in ("compliance_risk", "platform_risk"):
            with self.subTest(field=field):
                raw = base(); raw.pop(field)
                decision = evaluate(normalize(raw, now=NOW), now=NOW)
                self.assertEqual(decision.decision, "REVALIDATE")
                self.assertIn(field, decision.revalidation_fields)

    def test_explicit_supported_risks_are_preserved(self):
        for value in ("LOW", "MEDIUM", "HIGH"):
            raw = base(); raw["compliance_risk"] = value.lower(); raw["platform_risk"] = value
            op = normalize(raw, now=NOW)
            self.assertEqual(op["compliance_risk"], value)
            self.assertEqual(op["platform_risk"], value)
            self.assertEqual(evaluate(op, now=NOW).decision, "ACCEPT")

    def test_blocked_risk_is_hard_reject(self):
        for field in ("compliance_risk", "platform_risk"):
            with self.subTest(field=field):
                raw = base(); raw[field] = "BLOCKED"
                decision = evaluate(normalize(raw, now=NOW), now=NOW)
                self.assertEqual(decision.decision, "REJECT")
                self.assertEqual(decision.decision_reasons, ("RISK_BLOCKED",))
                self.assertFalse(decision.eligible_for_queue)


if __name__ == "__main__":
    unittest.main()
