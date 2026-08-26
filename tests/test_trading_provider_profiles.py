from __future__ import annotations

import unittest
from datetime import datetime, timezone

from workflow_os.trading_provider_profiles import tradeify_growth_25k_profile
from workflow_os.trading_provider_rules import assess_provider_readiness


class TradeifyGrowth25KProfileTests(unittest.TestCase):
    def test_profile_binds_current_official_rules_and_execution_surface(self) -> None:
        profile = tradeify_growth_25k_profile()

        self.assertEqual(profile.provider, "Tradeify")
        self.assertEqual(profile.account_size, 25_000)
        self.assertEqual(profile.purchase_cost, 99)
        self.assertEqual(profile.daily_loss_limit, 600)
        self.assertEqual(profile.max_drawdown, 1_000)
        self.assertEqual(profile.max_position_contracts, 1)
        self.assertEqual(profile.payout_share_pct, 90)
        self.assertEqual(profile.automation_state, "CONDITIONAL")
        self.assertFalse(profile.automation_requires_written_approval)
        self.assertEqual(profile.execution_access_state, "VERIFIED")
        self.assertFalse(profile.production_enabled)
        self.assertIn("HFT", profile.prohibited_strategies)
        self.assertIn("SHARED_BOT_ACROSS_FIRMS", profile.prohibited_strategies)

    def test_verified_provider_capability_still_cannot_enable_live_trading(self) -> None:
        decision = assess_provider_readiness(
            tradeify_growth_25k_profile(),
            now=datetime(2026, 8, 26, 0, 30, tzinfo=timezone.utc),
        )

        self.assertEqual(decision.decision, "HOLD")
        self.assertTrue(decision.may_simulate)
        self.assertFalse(decision.may_prepare_live_execution)
        self.assertEqual(decision.reasons, ("LIVE_TRADING_NOT_EXPLICITLY_ENABLED",))


if __name__ == "__main__":
    unittest.main()
