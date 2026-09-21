import unittest
from datetime import datetime, timedelta, timezone

from workflow_os.polymarket_paper import (
    PolymarketCandidate, PolymarketPaperPolicy, drawdown_decision, evaluate_candidate, should_exit,
)


class PolymarketPaperTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)

    def candidate(self, **overrides):
        values = dict(
            market_id="btc-friday", market_price=0.62, fair_probability=0.74,
            liquidity_usd=10_000.0, resolves_at=self.now + timedelta(hours=8),
            official_resolution_source_verified=True, estimated_exit_slippage=0.02,
        )
        values.update(overrides)
        return PolymarketCandidate(**values)

    def test_guide_example_is_capped_at_six_percent(self):
        result = evaluate_candidate(candidate=self.candidate(), bankroll_usd=50.0, open_positions=0, now_utc=self.now)
        self.assertEqual(result.action, "PAPER_BUY_YES")
        self.assertEqual(result.stake_usd, 3.0)
        self.assertAlmostEqual(result.edge_points, 12.0)

    def test_unverified_resolution_source_fails_closed(self):
        result = evaluate_candidate(candidate=self.candidate(official_resolution_source_verified=False), bankroll_usd=50.0, open_positions=0, now_utc=self.now)
        self.assertEqual((result.action, result.reason), ("HOLD", "UNVERIFIED_RESOLUTION_SOURCE"))

    def test_liquidity_and_slippage_gates_fail_closed(self):
        low = evaluate_candidate(candidate=self.candidate(liquidity_usd=4_999.0), bankroll_usd=50.0, open_positions=0, now_utc=self.now)
        slip = evaluate_candidate(candidate=self.candidate(estimated_exit_slippage=0.031), bankroll_usd=50.0, open_positions=0, now_utc=self.now)
        self.assertEqual(low.reason, "INSUFFICIENT_LIQUIDITY")
        self.assertEqual(slip.reason, "EXIT_LIQUIDITY_RISK")

    def test_two_hour_and_five_position_limits(self):
        close = evaluate_candidate(candidate=self.candidate(resolves_at=self.now + timedelta(minutes=119)), bankroll_usd=50.0, open_positions=0, now_utc=self.now)
        crowded = evaluate_candidate(candidate=self.candidate(), bankroll_usd=50.0, open_positions=5, now_utc=self.now)
        self.assertEqual(close.reason, "TOO_CLOSE_TO_RESOLUTION")
        self.assertEqual(crowded.reason, "OPEN_POSITION_LIMIT")

    def test_edge_must_exceed_eight_points(self):
        exact = evaluate_candidate(candidate=self.candidate(market_price=0.66), bankroll_usd=50.0, open_positions=0, now_utc=self.now)
        self.assertEqual((exact.action, exact.reason), ("HOLD", "EDGE_BELOW_THRESHOLD"))

    def test_forty_percent_peak_drawdown_stops(self):
        result = drawdown_decision(bankroll_usd=30.0, peak_bankroll_usd=50.0)
        self.assertEqual((result.action, result.reason), ("STOP", "DRAWDOWN_LIMIT"))

    def test_exit_rules_match_guide(self):
        self.assertEqual(should_exit(entry_fair_probability=.74, current_fair_probability=.74, hours_to_resolution=4, mispricing_closed=True).reason, "MISPRICING_CLOSED")
        self.assertEqual(should_exit(entry_fair_probability=.74, current_fair_probability=.68, hours_to_resolution=4, mispricing_closed=False).reason, "FAIR_VALUE_CHANGED")
        self.assertEqual(should_exit(entry_fair_probability=.74, current_fair_probability=.74, hours_to_resolution=1, mispricing_closed=False).reason, "RESOLUTION_WINDOW")


if __name__ == "__main__":
    unittest.main()
