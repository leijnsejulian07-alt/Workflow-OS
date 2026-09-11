import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from workflow_os.alpaca_paper_equity import build_alpaca_paper_equity_curve
from workflow_os.alpaca_paper_execution_costs import evaluate_paper_execution_economics
from workflow_os.alpaca_paper_order_outcome import AlpacaPaperOrderOutcome
from workflow_os.alpaca_paper_position_accounting import match_closed_long_paper_position
from workflow_os.alpaca_paper_position_evidence import record_alpaca_paper_position_evidence
from workflow_os.alpaca_paper_runtime import AlpacaPaperStrategyPolicy
from workflow_os.audit import AuditRevenueLedger


class AlpacaPaperEquityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "audit.db"
        self.audit = AuditRevenueLedger(self.path)
        self.policy = AlpacaPaperStrategyPolicy(strategy_id="minute-body-v1")

    def tearDown(self):
        self.tmp.cleanup()

    def _economics(self, *, client_order_id, side, reference, qty="2", symbol="AAPL"):
        outcome = AlpacaPaperOrderOutcome(
            external_order_id=f"external-{client_order_id}",
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            status="filled",
            ordered_qty=Decimal(qty),
            filled_qty=Decimal(qty),
            filled_avg_price=Decimal(reference),
            submitted_at=datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc),
            filled_at=datetime(2026, 9, 11, 10, 0, 1, tzinfo=timezone.utc),
            terminal=True,
        )
        return evaluate_paper_execution_economics(outcome=outcome, reference_price=reference)

    def _position(self, *, prefix, opening_reference, closing_reference):
        return match_closed_long_paper_position(
            opening=self._economics(
                client_order_id=f"{prefix}-open",
                side="buy",
                reference=opening_reference,
            ),
            closing=self._economics(
                client_order_id=f"{prefix}-close",
                side="sell",
                reference=closing_reference,
            ),
        )

    def _record(self, position, occurred_at, *, policy=None):
        return record_alpaca_paper_position_evidence(
            audit_ledger=self.audit,
            account_id="paper-account",
            strategy_policy=policy or self.policy,
            position=position,
            occurred_at=occurred_at,
        )

    def test_builds_chronological_equity_and_peak_to_trough_drawdown(self):
        winner = self._position(prefix="winner", opening_reference="100", closing_reference="110")
        loser = self._position(prefix="loser", opening_reference="110", closing_reference="100")
        self._record(winner, "2026-09-11T10:05:00Z")
        self._record(loser, "2026-09-11T11:05:00Z")

        curve = build_alpaca_paper_equity_curve(
            audit_ledger=self.audit,
            strategy_policy=self.policy,
            starting_equity_usd="1000",
        )

        self.assertEqual(curve.trade_count, 2)
        self.assertEqual(curve.points[0].paper_realized_pnl_usd, Decimal("19.370"))
        self.assertEqual(curve.points[0].equity_usd, Decimal("1019.370"))
        self.assertEqual(curve.points[0].drawdown_pct, Decimal("0"))
        self.assertEqual(curve.points[1].paper_realized_pnl_usd, Decimal("-20.630"))
        self.assertEqual(curve.ending_equity_usd, Decimal("998.740"))
        self.assertEqual(curve.net_paper_pnl_usd, Decimal("-1.260"))
        expected_drawdown = Decimal("20.630") / Decimal("1019.370") * Decimal("100")
        self.assertEqual(curve.max_drawdown_pct, expected_drawdown)
        self.assertFalse(curve.proves_received_cash)
        self.assertFalse(curve.proves_realized_cash_pnl)
        self.assertFalse(curve.may_enter_live_execution)

    def test_repeated_identical_position_observation_is_deduplicated(self):
        position = self._position(prefix="repeat", opening_reference="100", closing_reference="110")
        self._record(position, "2026-09-11T10:05:00Z")
        self._record(position, "2026-09-11T10:06:00Z")

        curve = build_alpaca_paper_equity_curve(
            audit_ledger=self.audit,
            strategy_policy=self.policy,
            starting_equity_usd="1000",
        )

        self.assertEqual(curve.trade_count, 1)
        self.assertEqual(curve.net_paper_pnl_usd, Decimal("19.370"))

    def test_conflicting_accounting_for_same_order_pair_fails_closed(self):
        position = self._position(prefix="conflict", opening_reference="100", closing_reference="110")
        self._record(position, "2026-09-11T10:05:00Z")
        conflicting = replace(
            position,
            gross_reference_pnl_usd=position.gross_reference_pnl_usd + Decimal("1"),
            paper_realized_pnl_usd=position.paper_realized_pnl_usd + Decimal("1"),
        )
        self._record(conflicting, "2026-09-11T10:06:00Z")

        with self.assertRaisesRegex(ValueError, "conflicting accounting evidence"):
            build_alpaca_paper_equity_curve(
                audit_ledger=self.audit,
                strategy_policy=self.policy,
                starting_equity_usd="1000",
            )

    def test_exact_strategy_policy_fingerprint_isolated_from_same_strategy_id(self):
        original_position = self._position(
            prefix="policy-original",
            opening_reference="100",
            closing_reference="110",
        )
        changed_position = self._position(
            prefix="policy-changed",
            opening_reference="100",
            closing_reference="90",
        )
        changed_policy = AlpacaPaperStrategyPolicy(
            strategy_id="minute-body-v1",
            minimum_body_bps=6.0,
        )
        self._record(original_position, "2026-09-11T10:05:00Z")
        self._record(
            changed_position,
            "2026-09-11T11:05:00Z",
            policy=changed_policy,
        )

        original_curve = build_alpaca_paper_equity_curve(
            audit_ledger=self.audit,
            strategy_policy=self.policy,
            starting_equity_usd="1000",
        )
        changed_curve = build_alpaca_paper_equity_curve(
            audit_ledger=self.audit,
            strategy_policy=changed_policy,
            starting_equity_usd="1000",
        )

        self.assertEqual(original_curve.trade_count, 1)
        self.assertEqual(original_curve.net_paper_pnl_usd, Decimal("19.370"))
        self.assertEqual(changed_curve.trade_count, 1)
        self.assertLess(changed_curve.net_paper_pnl_usd, Decimal("0"))

    def test_broken_audit_hash_chain_fails_closed(self):
        position = self._position(prefix="tamper", opening_reference="100", closing_reference="110")
        self._record(position, "2026-09-11T10:05:00Z")
        with sqlite3.connect(self.path) as db:
            db.execute(
                "UPDATE audit_events SET event_json=? WHERE event_type=?",
                ('{"tampered":true}', "trading.alpaca_paper_closed_position"),
            )

        with self.assertRaisesRegex(ValueError, "audit chain verification failed"):
            build_alpaca_paper_equity_curve(
                audit_ledger=self.audit,
                strategy_policy=self.policy,
                starting_equity_usd="1000",
            )

    def test_nonpositive_starting_equity_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "starting_equity_usd"):
            build_alpaca_paper_equity_curve(
                audit_ledger=self.audit,
                strategy_policy=self.policy,
                starting_equity_usd="0",
            )


if __name__ == "__main__":
    unittest.main()
