import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.ledger import OpportunityLedger
from workflow_os.opportunities import evaluate, normalize

NOW = datetime(2026, 8, 14, 1, 0, tzinfo=timezone.utc)


class OpportunityLedgerTests(unittest.TestCase):
    def raw(self, campaign_id="c1", revenue=100):
        return {
            "source_platform": "test",
            "campaign_id": campaign_id,
            "title": f"Campaign {campaign_id}",
            "category": "clipping",
            "usage_rights": "Verified licence",
            "rights_verification_state": "VERIFIED",
            "expected_revenue": revenue,
            "estimated_success_probability": 0.8,
            "probability_collection": 0.9,
            "expected_production_cost": 5,
            "expected_laptop_minutes": 30,
            "expected_owner_minutes": 0,
            "expected_time_to_cash_hours": 24,
            "automation_completeness": 1.0,
            "capital_required": 0,
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

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = OpportunityLedger(Path(self.tmp.name) / "workflow-os.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_records_and_reads_latest_decision(self):
        op = normalize(self.raw(), now=NOW)
        decision = evaluate(op, now=NOW)
        self.ledger.record(op, decision)
        stored = self.ledger.latest_decision(op["opportunity_id"])
        self.assertEqual(stored["decision"], "ACCEPT")
        self.assertTrue(stored["eligible_for_queue"])

    def test_record_is_idempotent_for_same_evaluation(self):
        op = normalize(self.raw(), now=NOW)
        decision = evaluate(op, now=NOW)
        self.ledger.record(op, decision)
        self.ledger.record(op, decision)
        self.assertEqual(len(self.ledger.queue_candidates()), 1)

    def test_only_latest_accepted_decisions_are_queue_candidates(self):
        op = normalize(self.raw(), now=NOW)
        accepted = evaluate(op, now=NOW)
        self.ledger.record(op, accepted)
        stale = dict(op)
        stale["source_checked_at"] = (NOW - timedelta(hours=3)).isoformat()
        revalidated = evaluate(stale, now=NOW + timedelta(seconds=1))
        self.ledger.record(stale, revalidated)
        self.assertEqual(revalidated.decision, "REVALIDATE")
        self.assertEqual(self.ledger.queue_candidates(), [])

    def test_backfilled_older_decision_cannot_replace_latest_queue_state(self):
        op = normalize(self.raw(), now=NOW)
        stale = dict(op)
        stale["source_checked_at"] = (NOW - timedelta(hours=3)).isoformat()
        newer = evaluate(stale, now=NOW + timedelta(minutes=10))
        older = evaluate(op, now=NOW)
        self.assertEqual(newer.decision, "REVALIDATE")
        self.assertEqual(older.decision, "ACCEPT")

        self.ledger.record(stale, newer)
        self.ledger.record(op, older)

        self.assertEqual(self.ledger.latest_decision(op["opportunity_id"])["decision"], "REVALIDATE")
        self.assertEqual(self.ledger.queue_candidates(), [])

    def test_queue_orders_by_priority(self):
        low = normalize(self.raw("low", 50), now=NOW)
        high = normalize(self.raw("high", 300), now=NOW)
        self.ledger.record(low, evaluate(low, now=NOW))
        self.ledger.record(high, evaluate(high, now=NOW))
        candidates = self.ledger.queue_candidates()
        self.assertEqual(candidates[0]["opportunity_id"], high["opportunity_id"])

    def test_rejects_mismatched_decision(self):
        first = normalize(self.raw("first"), now=NOW)
        second = normalize(self.raw("second"), now=NOW)
        with self.assertRaises(ValueError):
            self.ledger.record(first, evaluate(second, now=NOW))

    def test_queue_limit_is_bounded(self):
        with self.assertRaises(ValueError):
            self.ledger.queue_candidates(501)


if __name__ == "__main__":
    unittest.main()
