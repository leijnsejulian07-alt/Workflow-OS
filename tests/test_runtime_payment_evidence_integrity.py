import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.opportunities import evaluate, normalize

NOW = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)


class RuntimePaymentEvidenceIntegrityTests(unittest.TestCase):
    def accepted_opportunity(self):
        raw = {
            "source_platform": "test",
            "campaign_id": "payment-evidence",
            "title": "Payment evidence fixture",
            "category": "clipping",
            "usage_rights": "Verified campaign licence for intended publication",
            "rights_verification_state": "VERIFIED",
            "expected_revenue": 100,
            "estimated_success_probability": 0.5,
            "probability_collection": 0.8,
            "expected_production_cost": 5,
            "expected_laptop_minutes": 30,
            "expected_owner_minutes": 0,
            "expected_time_to_cash_hours": 48,
            "automation_completeness": 1.0,
            "capital_required": 0,
            "compliance_risk": "LOW",
            "platform_risk": "LOW",
            "duplicate_conflict_status": "CLEAR",
            "user_attention_requirement": "NONE",
            "source_checked_at": (NOW - timedelta(minutes=5)).isoformat(),
            "freshness_ttl_seconds": 3600,
            "deadline": (NOW + timedelta(days=2)).isoformat(),
            "remaining_budget": 1000,
            "payout_formula": "EUR 1 per qualified unit",
            "payout_cap": 500,
            "payment_method": "bank transfer",
            "approval_rules": "Qualified submission reviewed under campaign rules",
            "originality_requirements": "Original edit required",
            "account_requirements": ["verified creator account"],
        }
        op = normalize(raw, now=NOW)
        self.assertEqual(evaluate(op, now=NOW).decision, "ACCEPT")
        return op

    def assert_revalidates(self, field, value):
        op = self.accepted_opportunity()
        op[field] = value
        decision = evaluate(op, now=NOW)
        self.assertEqual(decision.decision, "REVALIDATE")
        self.assertFalse(decision.eligible_for_queue)
        self.assertIn(field, decision.revalidation_fields)

    def test_payout_cap_must_be_finite_nonnegative(self):
        for value in (None, "", -1, "unknown", float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                self.assert_revalidates("payout_cap", value)

    def test_payment_and_rule_text_must_be_explicit(self):
        for field in ("payment_method", "approval_rules", "originality_requirements"):
            for value in (None, "", "   ", [], 123):
                with self.subTest(field=field, value=value):
                    self.assert_revalidates(field, value)

    def test_account_requirements_must_be_bounded_string_list(self):
        for value in (None, "verified", ["ok", 123], [""], ["x"] * 65):
            with self.subTest(value=value):
                self.assert_revalidates("account_requirements", value)

    def test_valid_explicit_payment_evidence_remains_queue_eligible(self):
        op = self.accepted_opportunity()
        decision = evaluate(op, now=NOW)
        self.assertEqual(decision.decision, "ACCEPT")
        self.assertTrue(decision.eligible_for_queue)


if __name__ == "__main__":
    unittest.main()
