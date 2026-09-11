import unittest
from datetime import datetime, timezone
from decimal import Decimal

from workflow_os.alpaca_paper_execution_costs import (
    ALPACA_PAPER_EXECUTION_COST_POLICY_VERSION,
    AlpacaPaperExecutionCostPolicy,
    evaluate_paper_execution_economics,
)
from workflow_os.alpaca_paper_order_outcome import AlpacaPaperOrderOutcome


class AlpacaPaperExecutionCostsTests(unittest.TestCase):
    def _outcome(
        self,
        *,
        side="buy",
        status="filled",
        ordered_qty="2",
        filled_qty="2",
        filled_avg_price="101",
    ):
        return AlpacaPaperOrderOutcome(
            external_order_id="order-123",
            client_order_id="client-123",
            symbol="AAPL",
            side=side,
            status=status,
            ordered_qty=Decimal(ordered_qty),
            filled_qty=Decimal(filled_qty),
            filled_avg_price=None
            if filled_avg_price is None
            else Decimal(filled_avg_price),
            submitted_at=datetime(2026, 9, 11, 8, 30, tzinfo=timezone.utc),
            filled_at=None
            if Decimal(filled_qty) == 0
            else datetime(2026, 9, 11, 8, 30, 1, tzinfo=timezone.utc),
            terminal=status in {"filled", "canceled", "expired", "rejected"},
        )

    def test_adverse_buy_uses_observed_slippage_without_double_counting(self):
        economics = evaluate_paper_execution_economics(
            outcome=self._outcome(),
            reference_price="100",
        )
        self.assertEqual(economics.reference_notional_usd, Decimal("200"))
        self.assertEqual(economics.filled_notional_usd, Decimal("202"))
        self.assertEqual(economics.observed_adverse_slippage_bps, Decimal("100"))
        self.assertEqual(economics.modeled_slippage_bps, Decimal("100"))
        self.assertEqual(economics.modeled_slippage_usd, Decimal("2"))
        self.assertEqual(economics.modeled_fee_usd, Decimal("0.101"))
        self.assertEqual(economics.modeled_total_execution_cost_usd, Decimal("2.101"))
        self.assertEqual(economics.executed_cash_flow_usd, Decimal("-202"))
        self.assertEqual(economics.modeled_net_cash_flow_usd, Decimal("-202.101"))

    def test_favorable_fill_still_charges_conservative_slippage_floor(self):
        economics = evaluate_paper_execution_economics(
            outcome=self._outcome(filled_avg_price="99"),
            reference_price="100",
        )
        self.assertEqual(economics.observed_adverse_slippage_bps, Decimal("0"))
        self.assertEqual(economics.modeled_slippage_bps, Decimal("10"))
        self.assertEqual(economics.modeled_slippage_usd, Decimal("0.2"))
        self.assertEqual(economics.modeled_fee_usd, Decimal("0.099"))
        self.assertEqual(economics.executed_cash_flow_usd, Decimal("-198"))
        self.assertEqual(economics.modeled_net_cash_flow_usd, Decimal("-200.299"))

    def test_adverse_sell_is_symmetric_and_costs_reduce_proceeds(self):
        economics = evaluate_paper_execution_economics(
            outcome=self._outcome(side="sell", filled_avg_price="99"),
            reference_price="100",
        )
        self.assertEqual(economics.observed_adverse_slippage_bps, Decimal("100"))
        self.assertEqual(economics.modeled_slippage_usd, Decimal("2"))
        self.assertEqual(economics.modeled_fee_usd, Decimal("0.099"))
        self.assertEqual(economics.executed_cash_flow_usd, Decimal("198"))
        self.assertEqual(economics.modeled_net_cash_flow_usd, Decimal("197.901"))

    def test_partial_fill_costs_only_reconciled_quantity(self):
        economics = evaluate_paper_execution_economics(
            outcome=self._outcome(
                status="canceled",
                ordered_qty="2",
                filled_qty="0.5",
                filled_avg_price="100",
            ),
            reference_price="100",
        )
        self.assertEqual(economics.filled_qty, Decimal("0.5"))
        self.assertEqual(economics.reference_notional_usd, Decimal("50.0"))
        self.assertEqual(economics.filled_notional_usd, Decimal("50.0"))
        self.assertEqual(economics.modeled_slippage_usd, Decimal("0.050"))
        self.assertEqual(economics.modeled_fee_usd, Decimal("0.025"))
        self.assertEqual(economics.modeled_net_cash_flow_usd, Decimal("-50.075"))

    def test_no_fill_and_invalid_reference_fail_closed(self):
        no_fill = self._outcome(
            status="canceled",
            filled_qty="0",
            filled_avg_price=None,
        )
        with self.assertRaisesRegex(ValueError, "fill evidence"):
            evaluate_paper_execution_economics(
                outcome=no_fill,
                reference_price="100",
            )
        for value in ("0", "-1", "NaN", "Infinity", None, True):
            with self.subTest(reference_price=value):
                with self.assertRaises(ValueError):
                    evaluate_paper_execution_economics(
                        outcome=self._outcome(),
                        reference_price=value,
                    )

    def test_cost_policy_is_explicit_versioned_and_bounded(self):
        policy = AlpacaPaperExecutionCostPolicy(
            modeled_fee_bps=Decimal("7.5"),
            minimum_adverse_slippage_bps=Decimal("12.5"),
        )
        self.assertEqual(policy.modeled_fee_bps, Decimal("7.5"))
        self.assertEqual(policy.minimum_adverse_slippage_bps, Decimal("12.5"))
        self.assertEqual(policy.policy_version, ALPACA_PAPER_EXECUTION_COST_POLICY_VERSION)

        for kwargs in (
            {"modeled_fee_bps": Decimal("-1")},
            {"minimum_adverse_slippage_bps": Decimal("NaN")},
            {"modeled_fee_bps": Decimal("1000.1")},
            {"minimum_adverse_slippage_bps": Decimal("1000.1")},
            {"policy_version": "alpaca-paper-execution-cost/future"},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    AlpacaPaperExecutionCostPolicy(**kwargs)

    def test_execution_economics_never_proves_cash_pnl_or_live_authority(self):
        economics = evaluate_paper_execution_economics(
            outcome=self._outcome(),
            reference_price="100",
        )
        self.assertFalse(economics.proves_received_cash)
        self.assertFalse(economics.proves_realized_pnl)
        self.assertFalse(economics.may_enter_live_execution)


if __name__ == "__main__":
    unittest.main()
