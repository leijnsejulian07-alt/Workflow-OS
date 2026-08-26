import unittest

from workflow_os.trading_order_risk_gate import (
    TradingOrderIntent,
    TradingRiskSnapshot,
    evaluate_trading_order_risk,
)


class TradingOrderRiskGateTests(unittest.TestCase):
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
            idempotency_key="order-1",
            account_id="acct-1",
            symbol="MES",
            side="BUY",
            quantity_contracts=1,
            max_loss_if_filled=100,
        )
        values.update(changes)
        return TradingOrderIntent(**values)

    def test_healthy_bounded_intent_only_passes_to_side_effect_reservation(self):
        decision = evaluate_trading_order_risk(snapshot=self.snapshot(), intent=self.intent())
        self.assertEqual(decision.decision, "PASS_TO_SIDE_EFFECT_RESERVATION")
        self.assertTrue(decision.may_reserve_side_effect)
        self.assertEqual(decision.reasons, ())

    def test_production_disabled_holds(self):
        decision = evaluate_trading_order_risk(
            snapshot=self.snapshot(production_enabled=False), intent=self.intent()
        )
        self.assertFalse(decision.may_reserve_side_effect)
        self.assertIn("LIVE_TRADING_NOT_EXPLICITLY_ENABLED", decision.reasons)

    def test_kill_switch_and_unhealthy_reconciliation_hold(self):
        decision = evaluate_trading_order_risk(
            snapshot=self.snapshot(emergency_kill_switch=True, reconciliation_healthy=False),
            intent=self.intent(),
        )
        self.assertFalse(decision.may_reserve_side_effect)
        self.assertIn("EMERGENCY_KILL_SWITCH_ACTIVE", decision.reasons)
        self.assertIn("RECONCILIATION_UNHEALTHY", decision.reasons)

    def test_projected_loss_cannot_cross_daily_or_drawdown_limit(self):
        decision = evaluate_trading_order_risk(
            snapshot=self.snapshot(realized_daily_loss=550, current_drawdown=950),
            intent=self.intent(max_loss_if_filled=100),
        )
        self.assertFalse(decision.may_reserve_side_effect)
        self.assertIn("DAILY_LOSS_LIMIT_WOULD_BE_BREACHED", decision.reasons)
        self.assertIn("MAX_DRAWDOWN_WOULD_BE_BREACHED", decision.reasons)

    def test_position_limit_and_identity_drift_hold(self):
        position = evaluate_trading_order_risk(
            snapshot=self.snapshot(open_position_contracts=9.5),
            intent=self.intent(quantity_contracts=1),
        )
        self.assertIn("POSITION_LIMIT_WOULD_BE_BREACHED", position.reasons)
        identity = evaluate_trading_order_risk(
            snapshot=self.snapshot(), intent=self.intent(account_id="acct-other")
        )
        self.assertEqual(identity.reasons, ("ACCOUNT_IDENTITY_MISMATCH",))
        self.assertFalse(identity.may_reserve_side_effect)

    def test_invalid_side_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "side must be BUY or SELL"):
            evaluate_trading_order_risk(snapshot=self.snapshot(), intent=self.intent(side="HOLD"))


if __name__ == "__main__":
    unittest.main()
