import tempfile
import unittest
from pathlib import Path

from workflow_os.side_effects import SideEffectLedger
from workflow_os.trading_order_execution import (
    TradingOrderAttemptResult,
    TradingOrderReconciliationResult,
    execute_reserved_trading_order,
    reconcile_unknown_trading_order,
)
from workflow_os.trading_order_reservation import evaluate_and_reserve_trading_order
from workflow_os.trading_order_risk_gate import TradingOrderIntent, TradingRiskSnapshot


class TradingOrderExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.ledger = SideEffectLedger(Path(self.tempdir.name) / "side-effects.sqlite")

    def tearDown(self):
        self.tempdir.cleanup()

    def snapshot(self):
        return TradingRiskSnapshot(
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

    def intent(self, key="trade-order-1"):
        return TradingOrderIntent(
            idempotency_key=key,
            account_id="acct-1",
            symbol="MES",
            side="BUY",
            quantity_contracts=1,
            max_loss_if_filled=100,
        )

    def reserve(self, key="trade-order-1"):
        return evaluate_and_reserve_trading_order(
            ledger=self.ledger,
            snapshot=self.snapshot(),
            intent=self.intent(key),
        )

    def test_confirmed_applied_order_becomes_succeeded(self):
        reservation = self.reserve()
        result = execute_reserved_trading_order(
            reservation,
            ledger=self.ledger,
            submit=lambda: TradingOrderAttemptResult("APPLIED", "order-123"),
        )
        self.assertEqual(result.state, "SUCCEEDED")
        self.assertEqual(result.external_reference, "order-123")
        self.assertEqual(result.attempt_count, 1)

    def test_proven_not_applied_becomes_retryable(self):
        reservation = self.reserve()
        result = execute_reserved_trading_order(
            reservation,
            ledger=self.ledger,
            submit=lambda: TradingOrderAttemptResult("NOT_APPLIED"),
        )
        self.assertEqual(result.state, "FAILED_RETRYABLE")
        self.assertEqual(result.attempt_count, 1)

    def test_ambiguous_result_becomes_unknown(self):
        reservation = self.reserve()
        result = execute_reserved_trading_order(
            reservation,
            ledger=self.ledger,
            submit=lambda: TradingOrderAttemptResult("UNKNOWN"),
        )
        self.assertEqual(result.state, "UNKNOWN")
        with self.assertRaisesRegex(RuntimeError, "not execution-authorized"):
            execute_reserved_trading_order(
                reservation,
                ledger=self.ledger,
                submit=lambda: TradingOrderAttemptResult("APPLIED", "order-duplicate"),
            )

    def test_adapter_exception_becomes_unknown(self):
        reservation = self.reserve()

        def explode():
            raise TimeoutError("connection lost after dispatch")

        with self.assertRaises(TimeoutError):
            execute_reserved_trading_order(reservation, ledger=self.ledger, submit=explode)
        self.assertEqual(self.ledger.get("trade-order-1").state, "UNKNOWN")

    def test_unknown_can_reconcile_to_applied_without_redispatch(self):
        reservation = self.reserve()
        execute_reserved_trading_order(
            reservation,
            ledger=self.ledger,
            submit=lambda: TradingOrderAttemptResult("UNKNOWN"),
        )
        calls = []

        def probe():
            calls.append("probe")
            return TradingOrderReconciliationResult("FOUND_APPLIED", "order-456")

        result = reconcile_unknown_trading_order(
            ledger=self.ledger,
            idempotency_key="trade-order-1",
            reconcile=probe,
        )
        self.assertEqual(calls, ["probe"])
        self.assertEqual(result.state, "SUCCEEDED")
        self.assertEqual(result.external_reference, "order-456")
        self.assertEqual(result.attempt_count, 1)

    def test_unknown_can_reconcile_to_not_applied_then_retry_once(self):
        reservation = self.reserve()
        execute_reserved_trading_order(
            reservation,
            ledger=self.ledger,
            submit=lambda: TradingOrderAttemptResult("UNKNOWN"),
        )
        reconciled = reconcile_unknown_trading_order(
            ledger=self.ledger,
            idempotency_key="trade-order-1",
            reconcile=lambda: TradingOrderReconciliationResult("PROVEN_NOT_APPLIED"),
        )
        self.assertEqual(reconciled.state, "FAILED_RETRYABLE")
        retried = execute_reserved_trading_order(
            reservation,
            ledger=self.ledger,
            submit=lambda: TradingOrderAttemptResult("APPLIED", "order-789"),
        )
        self.assertEqual(retried.state, "SUCCEEDED")
        self.assertEqual(retried.attempt_count, 2)

    def test_still_unknown_remains_blocked(self):
        reservation = self.reserve()
        execute_reserved_trading_order(
            reservation,
            ledger=self.ledger,
            submit=lambda: TradingOrderAttemptResult("UNKNOWN"),
        )
        result = reconcile_unknown_trading_order(
            ledger=self.ledger,
            idempotency_key="trade-order-1",
            reconcile=lambda: TradingOrderReconciliationResult("STILL_UNKNOWN"),
        )
        self.assertEqual(result.state, "UNKNOWN")

    def test_reconciliation_requires_unknown_state(self):
        self.reserve()
        with self.assertRaisesRegex(RuntimeError, "only UNKNOWN"):
            reconcile_unknown_trading_order(
                ledger=self.ledger,
                idempotency_key="trade-order-1",
                reconcile=lambda: TradingOrderReconciliationResult("PROVEN_NOT_APPLIED"),
            )


if __name__ == "__main__":
    unittest.main()
