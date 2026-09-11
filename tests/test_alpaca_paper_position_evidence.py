import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from workflow_os.alpaca_paper_execution_costs import evaluate_paper_execution_economics
from workflow_os.alpaca_paper_order_outcome import AlpacaPaperOrderOutcome
from workflow_os.alpaca_paper_position_accounting import match_closed_long_paper_position
from workflow_os.alpaca_paper_position_evidence import record_alpaca_paper_position_evidence
from workflow_os.alpaca_paper_runtime import (
    AlpacaPaperStrategyPolicy,
    _strategy_policy_fingerprint,
)
from workflow_os.audit import AuditRevenueLedger


class AlpacaPaperPositionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "audit.db"
        self.audit = AuditRevenueLedger(self.path)
        self.strategy_policy = AlpacaPaperStrategyPolicy(strategy_id="minute-body-v1")
        self.position = match_closed_long_paper_position(
            opening=self._economics(
                client_order_id="open-1",
                side="buy",
                reference="100",
            ),
            closing=self._economics(
                client_order_id="close-1",
                side="sell",
                reference="110",
            ),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _economics(self, *, client_order_id, side, reference, symbol="AAPL", qty="2"):
        outcome = AlpacaPaperOrderOutcome(
            external_order_id=f"external-{client_order_id}",
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            status="filled",
            ordered_qty=Decimal(qty),
            filled_qty=Decimal(qty),
            filled_avg_price=Decimal(reference),
            submitted_at=datetime(2026, 9, 11, 10, 0, 0, tzinfo=timezone.utc),
            filled_at=datetime(2026, 9, 11, 10, 0, 2, tzinfo=timezone.utc),
            terminal=True,
        )
        return evaluate_paper_execution_economics(
            outcome=outcome,
            reference_price=reference,
        )

    def test_exact_replay_is_idempotent_and_never_becomes_cash_truth(self):
        kwargs = dict(
            audit_ledger=self.audit,
            account_id="paper-account",
            strategy_policy=self.strategy_policy,
            position=self.position,
            occurred_at="2026-09-11T10:05:00Z",
        )
        first = record_alpaca_paper_position_evidence(**kwargs)
        second = record_alpaca_paper_position_evidence(**kwargs)

        self.assertEqual(first, second)
        self.assertFalse(first.proves_received_cash)
        self.assertFalse(first.proves_realized_cash_pnl)
        self.assertFalse(first.may_enter_live_execution)
        self.assertEqual(self.audit.gross_cash_eur(), 0.0)
        self.assertTrue(self.audit.verify_audit_chain())

        with sqlite3.connect(self.path) as db:
            rows = db.execute(
                "SELECT event_json FROM audit_events "
                "WHERE event_type='trading.alpaca_paper_closed_position'"
            ).fetchall()
        self.assertEqual(len(rows), 1)
        payload = json.loads(rows[0][0])
        self.assertEqual(payload["mode"], "PAPER_ONLY")
        self.assertEqual(
            payload["strategy_policy_fingerprint"],
            _strategy_policy_fingerprint(self.strategy_policy),
        )
        self.assertEqual(payload["position"]["symbol"], "AAPL")
        self.assertEqual(payload["position"]["opening_client_order_id"], "open-1")
        self.assertEqual(payload["position"]["closing_client_order_id"], "close-1")
        self.assertEqual(payload["position"]["paper_realized_pnl_usd"], "19.370")
        self.assertFalse(payload["proves_received_cash"])
        self.assertFalse(payload["proves_realized_cash_pnl"])
        self.assertFalse(payload["may_enter_live_execution"])

    def test_later_observation_is_distinct_immutable_evidence(self):
        first = record_alpaca_paper_position_evidence(
            audit_ledger=self.audit,
            account_id="paper-account",
            strategy_policy=self.strategy_policy,
            position=self.position,
            occurred_at="2026-09-11T10:05:00Z",
        )
        second = record_alpaca_paper_position_evidence(
            audit_ledger=self.audit,
            account_id="paper-account",
            strategy_policy=self.strategy_policy,
            position=self.position,
            occurred_at="2026-09-11T10:06:00Z",
        )

        self.assertNotEqual(first.event_id, second.event_id)
        self.assertTrue(self.audit.verify_audit_chain())

    def test_tainted_or_inconsistent_position_fails_closed(self):
        invalid_positions = (
            replace(self.position, proves_received_cash=True),
            replace(self.position, proves_realized_cash_pnl=True),
            replace(self.position, may_enter_live_execution=True),
            replace(self.position, policy_version="alpaca-paper-position-accounting/future"),
            replace(
                self.position,
                paper_realized_pnl_usd=self.position.paper_realized_pnl_usd + Decimal("1"),
            ),
            replace(self.position, modeled_total_execution_cost_usd=Decimal("-1")),
            replace(self.position, closed_qty=Decimal("NaN")),
        )
        for position in invalid_positions:
            with self.subTest(position=position):
                with self.assertRaises(ValueError):
                    record_alpaca_paper_position_evidence(
                        audit_ledger=self.audit,
                        account_id="paper-account",
                        strategy_policy=self.strategy_policy,
                        position=position,
                        occurred_at="2026-09-11T10:05:00Z",
                    )

    def test_strategy_policy_is_part_of_evidence_identity(self):
        first = record_alpaca_paper_position_evidence(
            audit_ledger=self.audit,
            account_id="paper-account",
            strategy_policy=self.strategy_policy,
            position=self.position,
            occurred_at="2026-09-11T10:05:00Z",
        )
        changed_policy = AlpacaPaperStrategyPolicy(
            strategy_id="minute-body-v1",
            minimum_body_bps=6.0,
        )
        second = record_alpaca_paper_position_evidence(
            audit_ledger=self.audit,
            account_id="paper-account",
            strategy_policy=changed_policy,
            position=self.position,
            occurred_at="2026-09-11T10:05:00Z",
        )

        self.assertNotEqual(first.event_id, second.event_id)
        self.assertTrue(self.audit.verify_audit_chain())


if __name__ == "__main__":
    unittest.main()
