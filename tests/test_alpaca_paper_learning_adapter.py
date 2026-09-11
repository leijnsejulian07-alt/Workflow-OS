import unittest
from dataclasses import replace
from decimal import Decimal

from workflow_os.alpaca_paper_equity import AlpacaPaperEquityCurve, AlpacaPaperEquityPoint
from workflow_os.alpaca_paper_learning_adapter import (
    AlpacaPaperLearningContext,
    evaluate_alpaca_paper_equity_curve,
)
from workflow_os.trading_paper_learning import PaperLearningPolicy


class AlpacaPaperLearningAdapterTests(unittest.TestCase):
    def _curve(self, *, pnl="50", trade_count=60):
        points = tuple(
            AlpacaPaperEquityPoint(
                occurred_at=f"2026-09-{1 + (index // 24):02d}T{index % 24:02d}:00:00+00:00",
                symbol="AAPL",
                opening_client_order_id=f"open-{index}",
                closing_client_order_id=f"close-{index}",
                paper_realized_pnl_usd=Decimal(pnl) / Decimal(trade_count),
                cumulative_pnl_usd=Decimal(pnl) * Decimal(index + 1) / Decimal(trade_count),
                equity_usd=Decimal("1000") + Decimal(pnl) * Decimal(index + 1) / Decimal(trade_count),
                drawdown_pct=Decimal("0"),
            )
            for index in range(trade_count)
        )
        return AlpacaPaperEquityCurve(
            strategy_id="minute-body-v1",
            strategy_policy_fingerprint="a" * 64,
            starting_equity_usd=Decimal("1000"),
            ending_equity_usd=Decimal("1000") + Decimal(pnl),
            net_paper_pnl_usd=Decimal(pnl),
            modeled_execution_costs_usd=Decimal("5"),
            max_drawdown_pct=Decimal("0"),
            trade_count=trade_count,
            points=points,
        )

    def _drawdown_curve(self):
        points = []
        cumulative = Decimal("0")
        peak = Decimal("1000")
        max_drawdown = Decimal("0")
        for index in range(60):
            pnl = Decimal("200") if index == 0 else -(Decimal("150") / Decimal("59"))
            cumulative += pnl
            equity = Decimal("1000") + cumulative
            if equity > peak:
                peak = equity
            drawdown = (peak - equity) / peak * Decimal("100")
            if drawdown > max_drawdown:
                max_drawdown = drawdown
            points.append(
                AlpacaPaperEquityPoint(
                    occurred_at=f"2026-09-{1 + (index // 24):02d}T{index % 24:02d}:00:00+00:00",
                    symbol="AAPL",
                    opening_client_order_id=f"dd-open-{index}",
                    closing_client_order_id=f"dd-close-{index}",
                    paper_realized_pnl_usd=pnl,
                    cumulative_pnl_usd=cumulative,
                    equity_usd=equity,
                    drawdown_pct=drawdown,
                )
            )
        return AlpacaPaperEquityCurve(
            strategy_id="minute-body-v1",
            strategy_policy_fingerprint="a" * 64,
            starting_equity_usd=Decimal("1000"),
            ending_equity_usd=Decimal("1050"),
            net_paper_pnl_usd=Decimal("50"),
            modeled_execution_costs_usd=Decimal("5"),
            max_drawdown_pct=max_drawdown,
            trade_count=60,
            points=tuple(points),
        )

    def _context(self, **overrides):
        values = {
            "strategy_family": "minute-body",
            "strategy_version": "v1",
            "validation_start": "2026-08-20T00:00:00Z",
            "validation_end": "2026-09-10T00:00:00Z",
            "execution_error_count": 0,
            "ambiguous_side_effect_count": 0,
            "market_regimes": ("trend", "range"),
            "observed_at": "2026-09-11T15:00:00Z",
        }
        values.update(overrides)
        return AlpacaPaperLearningContext(**values)

    def test_positive_execution_derived_usd_results_can_be_green_without_fx(self):
        decision = evaluate_alpaca_paper_equity_curve(
            curve=self._curve(),
            context=self._context(),
        )

        self.assertEqual(decision.state, "PAPER_GREEN")
        self.assertEqual(decision.action, "KEEP_AS_INCUMBENT_CANDIDATE")
        self.assertFalse(decision.proves_received_cash)
        self.assertFalse(decision.may_enter_live_execution)

    def test_non_positive_usd_pnl_is_red(self):
        decision = evaluate_alpaca_paper_equity_curve(
            curve=self._curve(pnl="0"),
            context=self._context(),
        )

        self.assertEqual(decision.state, "PAPER_RED")
        self.assertIn("NON_POSITIVE_NET_PAPER_PNL", decision.reasons)

    def test_execution_derived_drawdown_breach_is_red(self):
        decision = evaluate_alpaca_paper_equity_curve(
            curve=self._drawdown_curve(),
            context=self._context(),
        )

        self.assertEqual(decision.state, "PAPER_RED")
        self.assertIn("PAPER_DRAWDOWN_TOO_HIGH", decision.reasons)

    def test_unresolved_ambiguous_side_effect_is_red(self):
        decision = evaluate_alpaca_paper_equity_curve(
            curve=self._curve(),
            context=self._context(ambiguous_side_effect_count=1),
        )

        self.assertEqual(decision.state, "PAPER_RED")
        self.assertIn("UNRESOLVED_AMBIGUOUS_SIDE_EFFECTS", decision.reasons)

    def test_insufficient_trade_count_is_amber(self):
        decision = evaluate_alpaca_paper_equity_curve(
            curve=self._curve(trade_count=10),
            context=self._context(),
        )

        self.assertEqual(decision.state, "PAPER_AMBER")
        self.assertIn("INSUFFICIENT_OOS_TRADES", decision.reasons)

    def test_execution_error_rate_uses_same_policy_boundary(self):
        decision = evaluate_alpaca_paper_equity_curve(
            curve=self._curve(trade_count=60),
            context=self._context(execution_error_count=2),
        )

        self.assertEqual(decision.state, "PAPER_RED")
        self.assertIn("EXECUTION_ERROR_RATE_TOO_HIGH", decision.reasons)

    def test_policy_thresholds_are_honored(self):
        decision = evaluate_alpaca_paper_equity_curve(
            curve=self._curve(trade_count=10),
            context=self._context(),
            policy=PaperLearningPolicy(min_validation_trades=10),
        )

        self.assertEqual(decision.state, "PAPER_GREEN")

    def test_fingerprint_is_deterministic_and_changes_with_context(self):
        curve = self._curve()
        first = evaluate_alpaca_paper_equity_curve(curve=curve, context=self._context())
        replay = evaluate_alpaca_paper_equity_curve(curve=curve, context=self._context())
        changed = evaluate_alpaca_paper_equity_curve(
            curve=curve,
            context=self._context(market_regimes=("trend", "volatile")),
        )

        self.assertEqual(first.window_fingerprint, replay.window_fingerprint)
        self.assertNotEqual(first.window_fingerprint, changed.window_fingerprint)

    def test_cash_or_live_authority_flags_fail_closed(self):
        curve = self._curve()
        for changed in (
            replace(curve, proves_received_cash=True),
            replace(curve, proves_realized_cash_pnl=True),
            replace(curve, may_enter_live_execution=True),
        ):
            with self.assertRaises(ValueError):
                evaluate_alpaca_paper_equity_curve(curve=changed, context=self._context())

    def test_inconsistent_trade_count_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "trade count"):
            evaluate_alpaca_paper_equity_curve(
                curve=replace(self._curve(), trade_count=61),
                context=self._context(),
            )

    def test_tampered_equity_accounting_fails_closed(self):
        curve = self._curve()
        with self.assertRaisesRegex(ValueError, "ending balance"):
            evaluate_alpaca_paper_equity_curve(
                curve=replace(curve, ending_equity_usd=Decimal("9999")),
                context=self._context(),
            )
        with self.assertRaisesRegex(ValueError, "max drawdown"):
            evaluate_alpaca_paper_equity_curve(
                curve=replace(curve, max_drawdown_pct=Decimal("1")),
                context=self._context(),
            )

    def test_context_must_not_claim_observation_before_validation_end(self):
        with self.assertRaisesRegex(ValueError, "observed_at"):
            self._context(observed_at="2026-09-09T23:59:59Z")


if __name__ == "__main__":
    unittest.main()
