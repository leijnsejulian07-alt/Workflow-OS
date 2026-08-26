from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from workflow_os.trading_account_health import (
    TradingAccountTelemetry,
    evaluate_trading_account_health,
)


NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


def healthy_telemetry(**overrides):
    data = dict(
        account_id="tradeify-growth25k-1",
        provider="TRADEIFY",
        program="GROWTH_25K",
        observed_at=NOW - timedelta(seconds=5),
        api_contract_version_expected="rithmic-v1",
        api_contract_version_observed="rithmic-v1",
        provider_rules_version_expected="tradeify-growth25k-2026-08-26",
        provider_rules_version_observed="tradeify-growth25k-2026-08-26",
        provider_rules_observed_at=NOW - timedelta(hours=2),
        reconciliation_healthy=True,
        unresolved_unknown_side_effects=0,
        current_drawdown=100.0,
        max_drawdown=1000.0,
        realized_daily_loss=50.0,
        daily_loss_limit=600.0,
        observed_slippage_bps=2.0,
        slippage_limit_bps=10.0,
        production_enabled=True,
    )
    data.update(overrides)
    return TradingAccountTelemetry(**data)


class TradingAccountHealthTests(unittest.TestCase):
    def test_healthy_account_can_feed_pre_order_gate(self):
        decision = evaluate_trading_account_health(
            telemetry=healthy_telemetry(), now=NOW
        )
        self.assertEqual("HEALTHY", decision.account_health)
        self.assertFalse(decision.automatic_pause)
        self.assertEqual((), decision.reasons)
        self.assertTrue(decision.rules_fresh)
        self.assertTrue(decision.reconciliation_healthy)

    def test_api_contract_mismatch_pauses(self):
        decision = evaluate_trading_account_health(
            telemetry=healthy_telemetry(api_contract_version_observed="rithmic-v2"),
            now=NOW,
        )
        self.assertEqual("PAUSED", decision.account_health)
        self.assertIn("API_CONTRACT_MISMATCH", decision.reasons)

    def test_provider_rule_drift_pauses(self):
        decision = evaluate_trading_account_health(
            telemetry=healthy_telemetry(
                provider_rules_version_observed="tradeify-growth25k-new"
            ),
            now=NOW,
        )
        self.assertFalse(decision.rules_fresh)
        self.assertIn("PROVIDER_RULE_VERSION_MISMATCH", decision.reasons)

    def test_stale_provider_rules_pause(self):
        decision = evaluate_trading_account_health(
            telemetry=healthy_telemetry(
                provider_rules_observed_at=NOW - timedelta(days=2)
            ),
            now=NOW,
            max_rule_age_seconds=86_400,
        )
        self.assertIn("PROVIDER_RULES_STALE", decision.reasons)
        self.assertFalse(decision.rules_fresh)

    def test_unresolved_unknown_side_effect_pauses(self):
        decision = evaluate_trading_account_health(
            telemetry=healthy_telemetry(unresolved_unknown_side_effects=1),
            now=NOW,
        )
        self.assertIn("UNRESOLVED_UNKNOWN_SIDE_EFFECTS", decision.reasons)
        self.assertFalse(decision.reconciliation_healthy)

    def test_reconciliation_failure_pauses(self):
        decision = evaluate_trading_account_health(
            telemetry=healthy_telemetry(reconciliation_healthy=False), now=NOW
        )
        self.assertIn("RECONCILIATION_UNHEALTHY", decision.reasons)

    def test_abnormal_slippage_pauses(self):
        decision = evaluate_trading_account_health(
            telemetry=healthy_telemetry(observed_slippage_bps=11.0), now=NOW
        )
        self.assertIn("ABNORMAL_SLIPPAGE", decision.reasons)

    def test_loss_and_drawdown_thresholds_pause(self):
        decision = evaluate_trading_account_health(
            telemetry=healthy_telemetry(
                realized_daily_loss=600.0, current_drawdown=1000.0
            ),
            now=NOW,
        )
        self.assertIn("DAILY_LOSS_LIMIT_REACHED", decision.reasons)
        self.assertIn("MAX_DRAWDOWN_REACHED", decision.reasons)

    def test_production_disabled_remains_paused(self):
        decision = evaluate_trading_account_health(
            telemetry=healthy_telemetry(production_enabled=False), now=NOW
        )
        self.assertIn("LIVE_TRADING_NOT_EXPLICITLY_ENABLED", decision.reasons)
        self.assertEqual("PAUSED", decision.account_health)

    def test_future_evidence_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "future"):
            evaluate_trading_account_health(
                telemetry=healthy_telemetry(observed_at=NOW + timedelta(seconds=1)),
                now=NOW,
            )


if __name__ == "__main__":
    unittest.main()
