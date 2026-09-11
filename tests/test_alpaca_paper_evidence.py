import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from workflow_os.alpaca_market_data import AlpacaLatestBarObservation
from workflow_os.alpaca_paper_evidence import record_alpaca_paper_runtime_evidence
from workflow_os.alpaca_paper_runtime import (
    AlpacaPaperDecision,
    AlpacaPaperRuntimeResult,
    AlpacaPaperStrategyPolicy,
    _strategy_policy_fingerprint,
)
from workflow_os.audit import AuditRevenueLedger
from workflow_os.side_effects import SideEffectRecord


class AlpacaPaperEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "audit.db"
        self.audit = AuditRevenueLedger(self.path)
        self.policy = AlpacaPaperStrategyPolicy(strategy_id="minute-body-v1")
        self.observation = AlpacaLatestBarObservation(
            symbol="AAPL",
            timestamp="2026-09-11T00:00:00Z",
            open=100.0,
            high=101.0,
            low=99.9,
            close=100.2,
            volume=1000,
            trade_count=10,
            vwap=100.1,
            request_id="market-rid",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_replay_is_idempotent_and_not_cash_truth(self):
        decision = AlpacaPaperDecision(
            "BUY", "DETERMINISTIC_LONG_SIGNAL", "wfos-paper-abc", None
        )
        effect = SideEffectRecord(
            idempotency_key="wfos-paper-abc",
            action="ALPACA_PAPER_ORDER",
            target="ALPACA_PAPER:paper-account",
            request_fingerprint="fingerprint",
            state="SUCCEEDED",
            attempt_count=1,
            max_attempts=2,
            external_reference="paper-order-1",
        )
        result = AlpacaPaperRuntimeResult("EXECUTED", self.observation, decision, effect)

        first = record_alpaca_paper_runtime_evidence(
            audit_ledger=self.audit,
            account_id="paper-account",
            policy=self.policy,
            result=result,
            occurred_at="2026-09-11T00:01:00Z",
        )
        second = record_alpaca_paper_runtime_evidence(
            audit_ledger=self.audit,
            account_id="paper-account",
            policy=self.policy,
            result=result,
            occurred_at="2026-09-11T00:01:00Z",
        )

        self.assertEqual(first, second)
        self.assertFalse(first.proves_received_cash)
        self.assertFalse(first.may_enter_live_execution)
        self.assertTrue(self.audit.verify_audit_chain())
        with sqlite3.connect(self.path) as db:
            row = db.execute(
                "SELECT event_json FROM audit_events WHERE event_type='trading.alpaca_paper_runtime'"
            ).fetchone()
            count = db.execute(
                "SELECT COUNT(*) FROM audit_events WHERE event_type='trading.alpaca_paper_runtime'"
            ).fetchone()[0]
        self.assertEqual(count, 1)
        payload = json.loads(row[0])
        self.assertEqual(
            payload["strategy_policy_fingerprint"],
            _strategy_policy_fingerprint(self.policy),
        )

    def test_no_observation_failure_is_replay_deterministic(self):
        result = AlpacaPaperRuntimeResult("NO_OBSERVATION", None, None, None)
        kwargs = dict(
            audit_ledger=self.audit,
            account_id="paper-account",
            policy=self.policy,
            result=result,
            occurred_at="2026-09-11T00:02:00Z",
        )
        first = record_alpaca_paper_runtime_evidence(**kwargs)
        second = record_alpaca_paper_runtime_evidence(**kwargs)
        self.assertEqual(first.event_id, second.event_id)
        self.assertEqual(first.event_hash, second.event_hash)
        self.assertTrue(self.audit.verify_audit_chain())

    def test_side_effect_state_transition_produces_new_evidence_event(self):
        decision = AlpacaPaperDecision(
            "BUY", "DETERMINISTIC_LONG_SIGNAL", "wfos-paper-abc", None
        )
        unknown = SideEffectRecord(
            "wfos-paper-abc",
            "ALPACA_PAPER_ORDER",
            "ALPACA_PAPER:paper-account",
            "fingerprint",
            "UNKNOWN",
            1,
            2,
            None,
        )
        succeeded = SideEffectRecord(
            "wfos-paper-abc",
            "ALPACA_PAPER_ORDER",
            "ALPACA_PAPER:paper-account",
            "fingerprint",
            "SUCCEEDED",
            1,
            2,
            "paper-order-1",
        )
        first = record_alpaca_paper_runtime_evidence(
            audit_ledger=self.audit,
            account_id="paper-account",
            policy=self.policy,
            result=AlpacaPaperRuntimeResult(
                "RECONCILE_REQUIRED", self.observation, decision, unknown
            ),
            occurred_at="2026-09-11T00:01:00Z",
        )
        second = record_alpaca_paper_runtime_evidence(
            audit_ledger=self.audit,
            account_id="paper-account",
            policy=self.policy,
            result=AlpacaPaperRuntimeResult(
                "RECONCILED", self.observation, decision, succeeded
            ),
            occurred_at="2026-09-11T00:02:00Z",
        )
        self.assertNotEqual(first.event_id, second.event_id)
        self.assertTrue(self.audit.verify_audit_chain())


if __name__ == "__main__":
    unittest.main()
