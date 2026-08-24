import unittest

from workflow_os.trading_simulation import (
    evaluate_simulation,
    may_prepare_live_execution,
    normalize_backtest,
    normalize_funded_account_rules,
)


def _backtest(**overrides):
    raw = {
        "strategy_id": "btc-momentum-v1",
        "engine": "vibetrading",
        "engine_version": "0.4.0",
        "symbols": ["BTC"],
        "starting_balance_eur": 10_000,
        "ending_balance_eur": 10_500,
        "realized_pnl_eur": 500,
        "fees_eur": 50,
        "max_drawdown_pct": 5,
        "trade_count": 40,
        "slippage_bps": 5,
        "evidence_sha256": "a" * 64,
        "observed_at": "2026-08-24T20:00:00+00:00",
    }
    raw.update(overrides)
    return raw


def _rules(**overrides):
    raw = {
        "provider": "example-prop-firm",
        "account_ref": "funded-account-1",
        "automation_allowed": True,
        "official_api_verified": True,
        "max_daily_loss_eur": 500,
        "max_total_drawdown_eur": 1_000,
        "max_position_notional_eur": 2_000,
        "max_leverage": 5,
        "allowed_symbols": ["BTC"],
        "rules_evidence_sha256": "b" * 64,
        "checked_at": "2026-08-24T20:00:00+00:00",
        "production_enabled": False,
    }
    raw.update(overrides)
    return raw


class TradingSimulationTests(unittest.TestCase):
    def test_backtest_pass_is_not_cash_or_live_authority(self):
        evidence = normalize_backtest(_backtest())
        decision = evaluate_simulation(evidence)

        self.assertFalse(evidence.proves_received_cash)
        self.assertEqual(decision.decision, "SIMULATION_PASS")
        self.assertTrue(decision.may_continue_simulation)
        self.assertFalse(decision.may_enter_live_execution)

    def test_backtest_pnl_must_match_balances(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            normalize_backtest(_backtest(realized_pnl_eur=999))

    def test_unknown_engine_and_malformed_digest_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "allowlisted"):
            normalize_backtest(_backtest(engine="remote-untrusted"))
        with self.assertRaisesRegex(ValueError, "evidence_sha256"):
            normalize_backtest(_backtest(evidence_sha256="ABC"))

    def test_loss_drawdown_and_small_sample_are_rejected(self):
        loss = normalize_backtest(
            _backtest(
                ending_balance_eur=9_500,
                realized_pnl_eur=-500,
                max_drawdown_pct=15,
                trade_count=5,
            )
        )
        decision = evaluate_simulation(loss)

        self.assertEqual(decision.decision, "REJECT")
        self.assertEqual(
            set(decision.reasons),
            {
                "NON_POSITIVE_BACKTEST_PNL",
                "BACKTEST_DRAWDOWN_TOO_HIGH",
                "INSUFFICIENT_BACKTEST_TRADES",
            },
        )
        self.assertFalse(decision.may_enter_live_execution)

    def test_funded_rules_require_independent_rule_evidence(self):
        with self.assertRaisesRegex(ValueError, "rules_evidence_sha256"):
            normalize_funded_account_rules(_rules(rules_evidence_sha256="unknown"))
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            normalize_funded_account_rules(_rules(checked_at="2026-08-24T20:00:00"))

    def test_live_preflight_stays_blocked_until_explicit_enablement(self):
        decision = evaluate_simulation(normalize_backtest(_backtest()))
        rules = normalize_funded_account_rules(_rules())

        allowed, reasons = may_prepare_live_execution(
            decision,
            rules,
            requested_symbol="BTC",
            requested_notional_eur=1_000,
            requested_leverage=2,
        )

        self.assertFalse(allowed)
        self.assertIn("LIVE_TRADING_NOT_EXPLICITLY_ENABLED", reasons)

    def test_live_preflight_rejects_platform_and_risk_limit_failures(self):
        decision = evaluate_simulation(normalize_backtest(_backtest()))
        rules = normalize_funded_account_rules(
            _rules(
                production_enabled=True,
                automation_allowed=False,
                official_api_verified=False,
            )
        )

        allowed, reasons = may_prepare_live_execution(
            decision,
            rules,
            requested_symbol="ETH",
            requested_notional_eur=5_000,
            requested_leverage=10,
        )

        self.assertFalse(allowed)
        self.assertEqual(
            set(reasons),
            {
                "FUNDED_ACCOUNT_AUTOMATION_NOT_ALLOWED",
                "OFFICIAL_API_NOT_VERIFIED",
                "SYMBOL_NOT_ALLOWED",
                "POSITION_NOTIONAL_EXCEEDS_LIMIT",
                "LEVERAGE_EXCEEDS_LIMIT",
            },
        )

    def test_all_preparation_gates_can_pass_without_emitting_an_order(self):
        decision = evaluate_simulation(normalize_backtest(_backtest()))
        rules = normalize_funded_account_rules(_rules(production_enabled=True))

        allowed, reasons = may_prepare_live_execution(
            decision,
            rules,
            requested_symbol="BTC",
            requested_notional_eur=1_000,
            requested_leverage=2,
        )

        self.assertTrue(allowed)
        self.assertEqual(reasons, ("PREPARE_ONLY_ALL_ACCOUNT_GATES_PASSED",))


if __name__ == "__main__":
    unittest.main()
