import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.audit import AuditRevenueLedger, CashReceipt
from workflow_os.ledger import OpportunityLedger
from workflow_os.opportunities import OpportunityDecision
from workflow_os.revenue_learning import MAX_REALIZED_CASH_BONUS, learning_signal, rank_accepted


class RevenueLearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "workflow-os.sqlite3"
        OpportunityLedger(self.path)
        self.ledger = AuditRevenueLedger(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def _persist_opportunity(self, opportunity_id: str, source_platform: str = "test") -> None:
        with sqlite3.connect(self.path) as db:
            db.execute(
                """
                INSERT INTO opportunities(
                    opportunity_id, normalized_json, source_platform, campaign_id,
                    discovered_at, updated_at
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    opportunity_id,
                    "{}",
                    source_platform,
                    "campaign-1",
                    "2026-08-20T12:00:00+00:00",
                    "2026-08-20T12:00:00+00:00",
                ),
            )

    def _decision(self, opportunity_id: str, *, priority: float = 50.0, decision: str = "ACCEPT", eligible: bool = True) -> OpportunityDecision:
        return OpportunityDecision(
            opportunity_id=opportunity_id,
            decision=decision,
            decision_reasons=("ELIGIBLE",),
            eligible_for_queue=eligible,
            economic_score=25.0,
            priority_score=priority,
            requires_revalidation=False,
            revalidation_fields=(),
            owner_attention_requirement="NONE",
            expected_collectible_revenue=100.0,
            expected_net_profit=80.0,
            expected_profit_per_laptop_hour=40.0,
            estimated_total_cost=20.0,
            risk_penalty=0.0,
            freshness_expires_at="2026-08-20T18:00:00+00:00",
            evaluated_at="2026-08-20T12:00:00+00:00",
        )

    def test_no_reconciled_cash_keeps_forecast_score(self):
        self._persist_opportunity("op-1")
        signal = learning_signal(self._decision("op-1", priority=61.0), self.ledger)
        self.assertEqual(signal.realized_cash_eur, 0.0)
        self.assertEqual(signal.realized_cash_bonus, 0.0)
        self.assertEqual(signal.learned_priority_score, 61.0)
        self.assertEqual(signal.evidence_state, "FORECAST_ONLY")

    def test_reconciled_attributed_cash_adds_bounded_bonus(self):
        self._persist_opportunity("op-1")
        self.ledger.record_cash(CashReceipt("r1", "test", 100.0, "2026-08-20T12:10:00+00:00", "payout-1"))
        self.ledger.attribute_cash("r1", "op-1", attributed_at="2026-08-20T12:11:00+00:00")
        signal = learning_signal(self._decision("op-1", priority=50.0), self.ledger)
        self.assertEqual(signal.realized_cash_eur, 100.0)
        self.assertEqual(signal.realized_cash_bonus, 10.0)
        self.assertEqual(signal.learned_priority_score, 60.0)
        self.assertEqual(signal.evidence_state, "RECONCILED_CASH")
        self.assertLessEqual(signal.realized_cash_bonus, MAX_REALIZED_CASH_BONUS)

    def test_cash_never_overrides_non_accept_gate(self):
        self._persist_opportunity("op-1")
        self.ledger.record_cash(CashReceipt("r1", "test", 500.0, "2026-08-20T12:10:00+00:00", "payout-1"))
        self.ledger.attribute_cash("r1", "op-1", attributed_at="2026-08-20T12:11:00+00:00")
        with self.assertRaises(ValueError):
            learning_signal(self._decision("op-1", decision="REJECT", eligible=False), self.ledger)

    def test_reconciled_cash_can_break_close_forecast_tie(self):
        self._persist_opportunity("op-cash")
        self._persist_opportunity("op-forecast")
        self.ledger.record_cash(CashReceipt("r1", "test", 100.0, "2026-08-20T12:10:00+00:00", "payout-1"))
        self.ledger.attribute_cash("r1", "op-cash", attributed_at="2026-08-20T12:11:00+00:00")
        ranked = rank_accepted(
            [self._decision("op-forecast", priority=55.0), self._decision("op-cash", priority=50.0)],
            self.ledger,
        )
        self.assertEqual([item.opportunity_id for item in ranked], ["op-cash", "op-forecast"])


if __name__ == "__main__":
    unittest.main()
