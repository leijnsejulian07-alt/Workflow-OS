import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from workflow_os.alpaca_paper_evidence import record_alpaca_paper_order_outcome_evidence
from workflow_os.alpaca_paper_order_outcome import AlpacaPaperOrderOutcome
from workflow_os.alpaca_paper_runtime import AlpacaPaperStrategyPolicy, _strategy_policy_fingerprint
from workflow_os.audit import AuditRevenueLedger


class AlpacaPaperOutcomeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "audit.db"
        self.audit = AuditRevenueLedger(self.path)
        self.policy = AlpacaPaperStrategyPolicy(strategy_id="minute-body-v1")

    def tearDown(self):
        self.tmp.cleanup()

    def _outcome(
        self,
        *,
        status="filled",
        filled_qty="0.01",
        filled_avg_price=Decimal("101.25"),
        filled_at=datetime(2026, 9, 11, 10, 0, 2, tzinfo=timezone.utc),
        terminal=True,
    ):
        return AlpacaPaperOrderOutcome(
            external_order_id="paper-order-1",
            client_order_id="wfos-paper-abc",
            symbol="AAPL",
            side="buy",
            status=status,
            ordered_qty=Decimal("0.01"),
            filled_qty=Decimal(filled_qty),
            filled_avg_price=filled_avg_price,
            submitted_at=datetime(2026, 9, 11, 10, 0, 0, tzinfo=timezone.utc),
            filled_at=filled_at,
            terminal=terminal,
        )

    def test_fill_evidence_is_idempotent_and_never_cash_truth(self):
        outcome = self._outcome()
        kwargs = dict(
            audit_ledger=self.audit,
            account_id="paper-account",
            policy=self.policy,
            outcome=outcome,
            occurred_at="2026-09-11T10:00:03Z",
        )
        first = record_alpaca_paper_order_outcome_evidence(**kwargs)
        second = record_alpaca_paper_order_outcome_evidence(**kwargs)

        self.assertEqual(first, second)
        self.assertFalse(first.proves_received_cash)
        self.assertFalse(first.may_enter_live_execution)
        self.assertEqual(self.audit.gross_cash_eur(), 0.0)
        self.assertTrue(self.audit.verify_audit_chain())

        with sqlite3.connect(self.path) as db:
            rows = db.execute(
                "SELECT event_json FROM audit_events "
                "WHERE event_type='trading.alpaca_paper_order_outcome'"
            ).fetchall()
        self.assertEqual(len(rows), 1)
        payload = json.loads(rows[0][0])
        self.assertEqual(
            payload["strategy_policy_fingerprint"],
            _strategy_policy_fingerprint(self.policy),
        )
        self.assertEqual(payload["order"]["filled_notional_usd"], "1.0125")
        self.assertFalse(payload["proves_received_cash"])
        self.assertFalse(payload["may_enter_live_execution"])

    def test_state_transition_creates_distinct_immutable_events(self):
        partial = self._outcome(
            status="partially_filled",
            filled_qty="0.005",
            filled_avg_price=Decimal("101.00"),
            terminal=False,
        )
        canceled = self._outcome(
            status="canceled",
            filled_qty="0.005",
            filled_avg_price=Decimal("101.00"),
            terminal=True,
        )
        first = record_alpaca_paper_order_outcome_evidence(
            audit_ledger=self.audit,
            account_id="paper-account",
            policy=self.policy,
            outcome=partial,
            occurred_at="2026-09-11T10:00:03Z",
        )
        second = record_alpaca_paper_order_outcome_evidence(
            audit_ledger=self.audit,
            account_id="paper-account",
            policy=self.policy,
            outcome=canceled,
            occurred_at="2026-09-11T10:00:04Z",
        )

        self.assertNotEqual(first.event_id, second.event_id)
        self.assertFalse(first.terminal)
        self.assertTrue(first.has_fill)
        self.assertTrue(second.terminal)
        self.assertTrue(second.has_fill)
        self.assertTrue(self.audit.verify_audit_chain())

    def test_same_snapshot_at_new_poll_time_is_separate_observation(self):
        outcome = self._outcome(
            status="new",
            filled_qty="0",
            filled_avg_price=None,
            filled_at=None,
            terminal=False,
        )
        first = record_alpaca_paper_order_outcome_evidence(
            audit_ledger=self.audit,
            account_id="paper-account",
            policy=self.policy,
            outcome=outcome,
            occurred_at="2026-09-11T10:00:03Z",
        )
        second = record_alpaca_paper_order_outcome_evidence(
            audit_ledger=self.audit,
            account_id="paper-account",
            policy=self.policy,
            outcome=outcome,
            occurred_at="2026-09-11T10:00:33Z",
        )
        self.assertNotEqual(first.event_id, second.event_id)
        self.assertTrue(self.audit.verify_audit_chain())


if __name__ == "__main__":
    unittest.main()
