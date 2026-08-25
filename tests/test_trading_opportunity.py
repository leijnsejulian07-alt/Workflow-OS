import unittest
from dataclasses import replace
from datetime import datetime, timezone

from workflow_os.opportunities import evaluate, normalize
from workflow_os.trading_opportunity import (
    TrustedTradingOpportunityEvidence,
    build_trading_opportunity,
)
from workflow_os.trading_simulation import evaluate_simulation, normalize_backtest


class TradingOpportunityTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 25, 10, 5, tzinfo=timezone.utc)
        self.backtest = normalize_backtest(
            {
                "strategy_id": "trend-following-eur-1",
                "engine": "workflow_os",
                "engine_version": "1.0",
                "symbols": ["EURUSD"],
                "starting_balance_eur": 10000,
                "ending_balance_eur": 10300,
                "realized_pnl_eur": 300,
                "fees_eur": 25,
                "max_drawdown_pct": 4.0,
                "trade_count": 80,
                "slippage_bps": 2.0,
                "evidence_sha256": "a" * 64,
                "observed_at": "2026-08-25T10:00:00+00:00",
            }
        )
        self.decision = evaluate_simulation(self.backtest)
        self.evidence = TrustedTradingOpportunityEvidence(
            strategy_rights_verified=True,
            forecast_verified=True,
            expected_revenue_eur=120.0,
            expected_cost_eur=10.0,
            expected_laptop_minutes=20.0,
            estimated_success_probability=0.7,
            probability_collection=0.9,
            expected_time_to_cash_hours=72.0,
            automation_completeness=0.95,
            capital_required_eur=0.0,
            payout_cap_eur=500.0,
            remaining_budget_eur=500.0,
            compliance_risk="MEDIUM",
            platform_risk="MEDIUM",
            duplicate_conflict_status="CLEAR",
            payout_formula="verified funded-account payout terms; forecast only",
            payment_method="verified funded-account payout method",
            approval_rules="owner approval plus funded-account live gates required",
            originality_requirements="strategy evidence must be independently verified",
            deadline="2026-09-01T00:00:00+00:00",
            freshness_ttl_seconds=3600,
            forecast_evidence_sha256="b" * 64,
        )

    def test_central_manager_surfaces_candidate_but_cannot_queue_live_order(self):
        raw = build_trading_opportunity(
            backtest=self.backtest,
            decision=self.decision,
            evidence=self.evidence,
        )
        self.assertEqual(raw["execution_mode"], "SIMULATION_ONLY")
        self.assertFalse(raw["live_execution_enabled"])
        self.assertFalse(raw["proves_received_cash"])

        opportunity = normalize(raw, now=self.now)
        decision = evaluate(opportunity, now=self.now)

        self.assertEqual(decision.decision, "PAUSE")
        self.assertFalse(decision.eligible_for_queue)
        self.assertEqual(decision.owner_attention_requirement, "OWNER_APPROVAL")
        self.assertIn("OWNER_ATTENTION_OWNER_APPROVAL", decision.decision_reasons)

    def test_rejected_simulation_cannot_enter_opportunity_admission(self):
        rejected_backtest = replace(self.backtest, realized_pnl_eur=-100.0, ending_balance_eur=9900.0)
        rejected = evaluate_simulation(rejected_backtest)
        self.assertEqual(rejected.decision, "REJECT")
        with self.assertRaisesRegex(ValueError, "passed trading simulation"):
            build_trading_opportunity(
                backtest=rejected_backtest,
                decision=rejected,
                evidence=self.evidence,
            )

    def test_forecast_cannot_exceed_verified_payout_cap(self):
        evidence = replace(self.evidence, expected_revenue_eur=501.0)
        with self.assertRaisesRegex(ValueError, "payout cap"):
            build_trading_opportunity(
                backtest=self.backtest,
                decision=self.decision,
                evidence=evidence,
            )

    def test_simulation_decision_cannot_self_grant_live_authority(self):
        hostile = replace(self.decision, may_enter_live_execution=True)
        with self.assertRaisesRegex(ValueError, "live execution authority"):
            build_trading_opportunity(
                backtest=self.backtest,
                decision=hostile,
                evidence=self.evidence,
            )

    def test_non_positive_collectible_margin_fails_closed(self):
        evidence = replace(
            self.evidence,
            expected_revenue_eur=10.0,
            expected_cost_eur=10.0,
            estimated_success_probability=0.5,
            probability_collection=0.5,
        )
        with self.assertRaisesRegex(ValueError, "non-positive expected collectible margin"):
            build_trading_opportunity(
                backtest=self.backtest,
                decision=self.decision,
                evidence=evidence,
            )


if __name__ == "__main__":
    unittest.main()
