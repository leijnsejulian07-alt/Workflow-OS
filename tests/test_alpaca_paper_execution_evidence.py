from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from workflow_os.alpaca_paper_execution_costs import evaluate_paper_execution_economics
from workflow_os.alpaca_paper_execution_evidence import (
    record_alpaca_paper_execution_economics_evidence,
)
from workflow_os.alpaca_paper_order_outcome import AlpacaPaperOrderOutcome
from workflow_os.alpaca_paper_runtime import (
    AlpacaPaperStrategyPolicy,
    _strategy_policy_fingerprint,
)
from workflow_os.audit import AuditRevenueLedger


class AlpacaPaperExecutionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "audit.db"
        self.audit = AuditRevenueLedger(self.path)
        self.strategy_policy = AlpacaPaperStrategyPolicy(strategy_id="minute-body-v1")
        self.outcome = AlpacaPaperOrderOutcome(
            external_order_id="paper-order-1",
            client_order_id="wfos-paper-abc",
            symbol="AAPL",
            side="buy",
            status="filled",
            ordered_qty=Decimal("2"),
            filled_qty=Decimal("2"),
            filled_avg_price=Decimal("101"),
            submitted_at=datetime(2026, 9, 11, 10, 0, 0, tzinfo=timezone.utc),
            filled_at=datetime(2026, 9, 11, 10, 0, 2, tzinfo=timezone.utc),
            terminal=True,
        )
        self.economics = evaluate_paper_execution_economics(
            outcome=self.outcome,
            reference_price="100",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_replay_is_idempotent_and_never_cash_or_live_truth(self):
        kwargs = dict(
            audit_ledger=self.audit,
            account_id="paper-account",
            strategy_policy=self.strategy_policy,
            economics=self.economics,
            occurred_at="2026-09-11T10:00:03Z",
        )
        first = record_alpaca_paper_execution_economics_evidence(**kwargs)
        second = record_alpaca_paper_execution_economics_evidence(**kwargs)

        self.assertEqual(first, second)
        self.assertFalse(first.proves_received_cash)
        self.assertFalse(first.proves_realized_pnl)
        self.assertFalse(first.may_enter_live_execution)
        self.assertEqual(self.audit.gross_cash_eur(), 0.0)
        self.assertTrue(self.audit.verify_audit_chain())

        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute(
                "SELECT event_json FROM audit_events "
                "WHERE event_type='trading.alpaca_paper_execution_economics'"
            ).fetchall()
        self.assertEqual(len(rows), 1)
        payload = json.loads(rows[0][0])
        self.assertEqual(
            payload["strategy_policy_fingerprint"],
            _strategy_policy_fingerprint(self.strategy_policy),
        )
        self.assertEqual(payload["execution"]["symbol"], "AAPL")
        self.assertEqual(Decimal(payload["execution"]["observed_adverse_slippage_bps"]), Decimal("100"))
        self.assertEqual(payload["execution"]["modeled_total_execution_cost_usd"], "2.101")
        self.assertEqual(payload["execution"]["modeled_net_cash_flow_usd"], "-202.101")
        self.assertFalse(payload["proves_received_cash"])
        self.assertFalse(payload["proves_realized_pnl"])
        self.assertFalse(payload["may_enter_live_execution"])

    def test_new_observation_time_produces_distinct_immutable_evidence(self):
        first = record_alpaca_paper_execution_economics_evidence(
            audit_ledger=self.audit,
            account_id="paper-account",
            strategy_policy=self.strategy_policy,
            economics=self.economics,
            occurred_at="2026-09-11T10:00:03Z",
        )
        second = record_alpaca_paper_execution_economics_evidence(
            audit_ledger=self.audit,
            account_id="paper-account",
            strategy_policy=self.strategy_policy,
            economics=self.economics,
            occurred_at="2026-09-11T10:00:33Z",
        )
        self.assertNotEqual(first.event_id, second.event_id)
        self.assertTrue(self.audit.verify_audit_chain())

    def test_tainted_economics_cannot_be_persisted_as_safe_paper_evidence(self):
        for economics in (
            replace(self.economics, proves_received_cash=True),
            replace(self.economics, proves_realized_pnl=True),
            replace(self.economics, may_enter_live_execution=True),
            replace(self.economics, policy_version="alpaca-paper-execution-cost/future"),
        ):
            with self.subTest(economics=economics):
                with self.assertRaises(ValueError):
                    record_alpaca_paper_execution_economics_evidence(
                        audit_ledger=self.audit,
                        account_id="paper-account",
                        strategy_policy=self.strategy_policy,
                        economics=economics,
                        occurred_at="2026-09-11T10:00:03Z",
                    )


if __name__ == "__main__":
    unittest.main()
