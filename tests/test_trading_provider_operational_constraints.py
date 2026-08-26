from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from workflow_os.trading_provider_operational_constraints import (
    assess_operational_compliance,
    tradeify_growth_operational_constraints,
)


class TradingProviderOperationalConstraintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.constraints = tradeify_growth_operational_constraints()
        self.now = datetime(2026, 8, 26, 0, 30, tzinfo=timezone.utc)

    def test_tradeify_profile_captures_current_duration_and_idle_rules(self) -> None:
        self.assertEqual(self.constraints.minimum_trade_duration_seconds, 10.0)
        self.assertEqual(self.constraints.minimum_trade_share_at_or_above_duration_pct, 50.0)
        self.assertEqual(self.constraints.minimum_profit_share_at_or_above_duration_pct, 50.0)
        self.assertEqual(self.constraints.max_idle_calendar_days, 7)

    def test_payout_eligible_batch_passes_without_authorizing_execution(self) -> None:
        decision = assess_operational_compliance(
            self.constraints,
            trade_durations_seconds=[12, 15, 5, 20],
            realized_trade_profits=[40, 35, 10, 15],
            last_trade_at=self.now - timedelta(days=1),
            now=self.now,
        )

        self.assertEqual(decision.decision, "ELIGIBLE")
        self.assertEqual(decision.reasons, ("OPERATIONAL_CONSTRAINTS_PASSED",))
        self.assertEqual(decision.qualifying_trade_share_pct, 75.0)
        self.assertEqual(decision.qualifying_profit_share_pct, 90.0)

    def test_exactly_half_trade_duration_share_is_fail_closed(self) -> None:
        decision = assess_operational_compliance(
            self.constraints,
            trade_durations_seconds=[10, 11, 9, 8],
            realized_trade_profits=[25, 25, 25, 25],
            last_trade_at=self.now - timedelta(days=1),
            now=self.now,
        )

        self.assertEqual(decision.decision, "HOLD")
        self.assertIn("TRADE_DURATION_SHARE_NOT_PAYOUT_ELIGIBLE", decision.reasons)
        self.assertIn("PROFIT_DURATION_SHARE_NOT_PAYOUT_ELIGIBLE", decision.reasons)

    def test_losses_cannot_make_short_trade_profit_share_look_compliant(self) -> None:
        decision = assess_operational_compliance(
            self.constraints,
            trade_durations_seconds=[15, 15, 5, 5],
            realized_trade_profits=[20, 20, 100, -500],
            last_trade_at=self.now - timedelta(days=1),
            now=self.now,
        )

        self.assertEqual(decision.decision, "HOLD")
        self.assertIn("TRADE_DURATION_SHARE_NOT_PAYOUT_ELIGIBLE", decision.reasons)
        self.assertIn("PROFIT_DURATION_SHARE_NOT_PAYOUT_ELIGIBLE", decision.reasons)
        self.assertAlmostEqual(decision.qualifying_profit_share_pct, 28.5714285714)

    def test_idle_account_is_held(self) -> None:
        decision = assess_operational_compliance(
            self.constraints,
            trade_durations_seconds=[20, 20, 20],
            realized_trade_profits=[10, 10, 10],
            last_trade_at=self.now - timedelta(days=8),
            now=self.now,
        )

        self.assertEqual(decision.decision, "HOLD")
        self.assertIn("ACCOUNT_IDLE_LIMIT_EXCEEDED", decision.reasons)

    def test_no_trade_evidence_holds(self) -> None:
        decision = assess_operational_compliance(
            self.constraints,
            trade_durations_seconds=[],
            realized_trade_profits=[],
            last_trade_at=self.now,
            now=self.now,
        )

        self.assertEqual(decision.decision, "HOLD")
        self.assertEqual(decision.reasons, ("NO_TRADE_EVIDENCE",))

    def test_mismatched_trade_evidence_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "equal length"):
            assess_operational_compliance(
                self.constraints,
                trade_durations_seconds=[20],
                realized_trade_profits=[10, 20],
                last_trade_at=self.now,
                now=self.now,
            )


if __name__ == "__main__":
    unittest.main()
