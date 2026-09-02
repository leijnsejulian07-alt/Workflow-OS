from __future__ import annotations

import unittest

from workflow_os.trading_paper_learning import (
    ALLOWED_PAPER_ENDPOINT,
    FundedReadinessDecision,
    PaperLearningPolicy,
    PaperStrategyWindow,
    choose_strategy_action,
    evaluate_funded_readiness,
    evaluate_paper_window,
)

DIGEST = "a" * 64


def window(**overrides):
    values = dict(
        strategy_id="trend-001",
        strategy_family="trend",
        strategy_version="v3",
        provider="alpaca",
        endpoint=ALLOWED_PAPER_ENDPOINT,
        train_start="2026-01-01T00:00:00+00:00",
        train_end="2026-01-31T00:00:00+00:00",
        validation_start="2026-02-01T00:00:00+00:00",
        validation_end="2026-02-20T00:00:00+00:00",
        trade_count=80,
        net_pnl_eur=125.0,
        modeled_fees_eur=15.0,
        modeled_slippage_eur=25.0,
        max_drawdown_pct=4.5,
        execution_error_count=0,
        ambiguous_side_effect_count=0,
        market_regimes=("trend", "volatile"),
        evidence_sha256=DIGEST,
        observed_at="2026-02-20T01:00:00+00:00",
    )
    values.update(overrides)
    return PaperStrategyWindow(**values)


class PaperLearningTests(unittest.TestCase):
    def test_rejects_live_endpoint_and_overlapping_windows(self):
        with self.assertRaisesRegex(ValueError, "paper endpoint"):
            window(endpoint="https://api.alpaca.markets")
        with self.assertRaisesRegex(ValueError, "chronological"):
            window(validation_start="2026-01-20T00:00:00+00:00")

    def test_paper_evidence_can_never_be_cash_or_live_authority(self):
        with self.assertRaisesRegex(ValueError, "received cash"):
            window(proves_received_cash=True)
        with self.assertRaisesRegex(ValueError, "live execution"):
            window(may_enter_live_execution=True)

    def test_hard_failure_turns_strategy_red_and_requests_replacement(self):
        decision = evaluate_paper_window(window(net_pnl_eur=-1.0, ambiguous_side_effect_count=1))
        self.assertEqual(decision.state, "PAPER_RED")
        self.assertEqual(decision.action, "PAUSE_OR_REPLACE_STRATEGY")
        self.assertIn("NON_POSITIVE_NET_PAPER_PNL", decision.reasons)
        self.assertIn("UNRESOLVED_AMBIGUOUS_SIDE_EFFECTS", decision.reasons)
        self.assertFalse(decision.may_enter_live_execution)

    def test_small_sample_stays_amber(self):
        decision = evaluate_paper_window(window(trade_count=10, validation_end="2026-02-06T00:00:00+00:00", market_regimes=("trend",)))
        self.assertEqual(decision.state, "PAPER_AMBER")
        self.assertEqual(decision.action, "CONTINUE_PAPER_VALIDATION")

    def test_robust_window_is_green_but_still_paper_only(self):
        decision = evaluate_paper_window(window())
        self.assertEqual(decision.state, "PAPER_GREEN")
        self.assertFalse(decision.may_enter_live_execution)
        self.assertFalse(decision.proves_received_cash)

    def test_red_incumbent_causes_strategy_family_exploration(self):
        incumbent = evaluate_paper_window(window(net_pnl_eur=-10.0))
        self.assertEqual(choose_strategy_action(incumbent=incumbent, challenger=None), "EXPLORE_DIFFERENT_STRATEGY_FAMILY")

    def test_green_challenger_can_replace_failed_incumbent_for_next_paper_window(self):
        incumbent = evaluate_paper_window(window(net_pnl_eur=-10.0))
        challenger = evaluate_paper_window(window(strategy_id="meanrev-001", strategy_family="mean-reversion"))
        self.assertEqual(choose_strategy_action(incumbent=incumbent, challenger=challenger), "PROMOTE_CHALLENGER_FOR_NEXT_PAPER_WINDOW")

    def test_funded_ready_requires_sustained_non_overlapping_green_oos_windows(self):
        windows = [
            window(validation_start="2026-02-01T00:00:00+00:00", validation_end="2026-02-15T00:00:00+00:00", observed_at="2026-02-15T01:00:00+00:00"),
            window(train_start="2026-01-15T00:00:00+00:00", train_end="2026-02-14T00:00:00+00:00", validation_start="2026-02-15T00:00:00+00:00", validation_end="2026-03-01T00:00:00+00:00", observed_at="2026-03-01T01:00:00+00:00"),
            window(train_start="2026-02-01T00:00:00+00:00", train_end="2026-02-28T00:00:00+00:00", validation_start="2026-03-01T00:00:00+00:00", validation_end="2026-03-15T00:00:00+00:00", observed_at="2026-03-15T01:00:00+00:00"),
        ]
        decision = evaluate_funded_readiness(windows)
        self.assertEqual(decision.state, "FUNDED_READY")
        self.assertFalse(decision.may_purchase_funded_account)
        self.assertFalse(decision.may_request_live_credentials)
        self.assertFalse(decision.may_enter_live_execution)

    def test_overlapping_green_windows_do_not_reach_funded_ready(self):
        windows = [
            window(validation_start="2026-02-01T00:00:00+00:00", validation_end="2026-02-20T00:00:00+00:00"),
            window(train_start="2026-01-10T00:00:00+00:00", train_end="2026-01-31T00:00:00+00:00", validation_start="2026-02-10T00:00:00+00:00", validation_end="2026-02-28T00:00:00+00:00"),
            window(train_start="2026-02-01T00:00:00+00:00", train_end="2026-02-28T00:00:00+00:00", validation_start="2026-03-01T00:00:00+00:00", validation_end="2026-03-20T00:00:00+00:00"),
        ]
        decision = evaluate_funded_readiness(windows)
        self.assertEqual(decision.state, "PAPER_AMBER")
        self.assertIn("QUALIFYING_OOS_WINDOWS_OVERLAP", decision.reasons)


if __name__ == "__main__":
    unittest.main()
