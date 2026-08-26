import tempfile
import unittest
from pathlib import Path

from workflow_os.side_effects import SideEffectLedger
from workflow_os.trading_order_reservation import evaluate_and_reserve_trading_order
from workflow_os.trading_order_risk_gate import TradingOrderIntent, TradingRiskSnapshot


class TradingOrderReservationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.ledger = SideEffectLedger(Path(self.tempdir.name) / "side-effects.sqlite")

    def tearDown(self):
        self.tempdir.cleanup()

    def snapshot(self, **changes):
        values = dict(
            account_id="acct-1",
            provider="TRADEIFY",
            program="GROWTH-25K",
            daily_loss_limit=600,
            max_drawdown=1000,
            max_position_contracts=10,
            realized_daily_loss=100,
            current_drawdown=200,
            open_position_contracts=2,
            account_health="HEALTHY",
            emergency_kill_switch=False,
            rules_fresh=True,
            reconciliation_healthy=True,
            production_enabled=True,
        )
        values.update(changes)
        return TradingRiskSnapshot(**values)

    def intent(self, **changes):
        values = dict(
            idempotency_key="trade-order-1",
            account_id="acct-1",
            symbol="MES",
            side="BUY",
            quantity_contracts=1,
            max_loss_if_filled=100,
        )
        values.update(changes)
        return TradingOrderIntent(**values)

    def test_pass_only_reserves_and_does_not_begin_execution(self):
        result = evaluate_and_reserve_trading_order(
            ledger=self.ledger, snapshot=self.snapshot(), intent=self.intent()
        )
        self.assertTrue(result.reserved)
        self.assertEqual(result.reservation.state, "RESERVED")
        self.assertEqual(result.reservation.action, "TRADING_ORDER")
        self.assertEqual(result.reservation.target, "TRADEIFY:acct-1")
        self.assertEqual(result.reservation.attempt_count, 0)

    def test_hold_creates_no_side_effect_record(self):
        result = evaluate_and_reserve_trading_order(
            ledger=self.ledger,
            snapshot=self.snapshot(production_enabled=False),
            intent=self.intent(),
        )
        self.assertFalse(result.reserved)
        self.assertIsNone(self.ledger.get("trade-order-1"))
        self.assertIn("LIVE_TRADING_NOT_EXPLICITLY_ENABLED", result.decision.reasons)

    def test_exact_replay_is_idempotent(self):
        first = evaluate_and_reserve_trading_order(
            ledger=self.ledger, snapshot=self.snapshot(), intent=self.intent()
        )
        second = evaluate_and_reserve_trading_order(
            ledger=self.ledger, snapshot=self.snapshot(), intent=self.intent()
        )
        self.assertEqual(first.reservation.request_fingerprint, second.reservation.request_fingerprint)
        self.assertEqual(second.reservation.state, "RESERVED")
        self.assertEqual(second.reservation.attempt_count, 0)

    def test_same_key_cannot_bind_to_changed_order(self):
        evaluate_and_reserve_trading_order(
            ledger=self.ledger, snapshot=self.snapshot(), intent=self.intent()
        )
        with self.assertRaisesRegex(ValueError, "different side effect"):
            evaluate_and_reserve_trading_order(
                ledger=self.ledger,
                snapshot=self.snapshot(),
                intent=self.intent(quantity_contracts=2),
            )

    def test_progressed_side_effect_cannot_be_freshly_reserved_again(self):
        evaluate_and_reserve_trading_order(
            ledger=self.ledger, snapshot=self.snapshot(), intent=self.intent()
        )
        self.ledger.begin_attempt("trade-order-1")
        with self.assertRaisesRegex(RuntimeError, "not fresh/reservable"):
            evaluate_and_reserve_trading_order(
                ledger=self.ledger, snapshot=self.snapshot(), intent=self.intent()
            )


if __name__ == "__main__":
    unittest.main()
