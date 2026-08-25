import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from workflow_os.audit import AuditRevenueLedger
from workflow_os.experiment_ledger import ExperimentLedger
from workflow_os.trading_experiment_evidence import record_trading_simulation_result
from workflow_os.trading_simulation import evaluate_simulation, normalize_backtest


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
        "observed_at": "2026-08-25T10:00:00+00:00",
    }
    raw.update(overrides)
    return raw


class TradingExperimentEvidenceTests(unittest.TestCase):
    def _ledgers(self, root: Path):
        return (
            AuditRevenueLedger(root / "audit.sqlite"),
            ExperimentLedger(root / "experiments.sqlite"),
        )

    def test_pass_reserves_shared_experiment_and_audits_without_cash_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit, experiments = self._ledgers(Path(tmp))
            evidence = normalize_backtest(_backtest())
            decision = evaluate_simulation(evidence)

            result = record_trading_simulation_result(
                audit_ledger=audit,
                experiment_ledger=experiments,
                evidence=evidence,
                decision=decision,
            )

            self.assertEqual(result.status, "RESERVED_SIMULATION_EXPERIMENT")
            self.assertFalse(result.proves_received_cash)
            self.assertIsNotNone(result.reservation)
            stored = experiments.get(result.experiment_opportunity_id)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.experiment_key, result.experiment_key)
            self.assertTrue(audit.verify_audit_chain())
            self.assertEqual(audit.gross_cash_eur(), 0.0)

    def test_exact_replay_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit, experiments = self._ledgers(Path(tmp))
            evidence = normalize_backtest(_backtest())
            decision = evaluate_simulation(evidence)

            first = record_trading_simulation_result(
                audit_ledger=audit,
                experiment_ledger=experiments,
                evidence=evidence,
                decision=decision,
            )
            second = record_trading_simulation_result(
                audit_ledger=audit,
                experiment_ledger=experiments,
                evidence=evidence,
                decision=decision,
            )

            self.assertEqual(first.experiment_key, second.experiment_key)
            self.assertEqual(first.audit_event_hash, second.audit_event_hash)
            self.assertEqual(first.reservation, second.reservation)

    def test_rejected_backtest_is_audited_but_not_reserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit, experiments = self._ledgers(Path(tmp))
            evidence = normalize_backtest(
                _backtest(
                    ending_balance_eur=9_500,
                    realized_pnl_eur=-500,
                    max_drawdown_pct=15,
                    trade_count=5,
                )
            )
            decision = evaluate_simulation(evidence)

            result = record_trading_simulation_result(
                audit_ledger=audit,
                experiment_ledger=experiments,
                evidence=evidence,
                decision=decision,
            )

            self.assertEqual(result.status, "RECORDED_REJECTED")
            self.assertIsNone(result.reservation)
            self.assertIsNone(experiments.get(result.experiment_opportunity_id))
            self.assertTrue(audit.verify_audit_chain())
            self.assertEqual(audit.gross_cash_eur(), 0.0)

    def test_strategy_identity_drift_fails_closed_before_reservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit, experiments = self._ledgers(Path(tmp))
            evidence = normalize_backtest(_backtest())
            decision = replace(evaluate_simulation(evidence), strategy_id="other")

            with self.assertRaisesRegex(ValueError, "identity mismatch"):
                record_trading_simulation_result(
                    audit_ledger=audit,
                    experiment_ledger=experiments,
                    evidence=evidence,
                    decision=decision,
                )

    def test_simulation_can_never_claim_received_cash_or_live_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit, experiments = self._ledgers(Path(tmp))
            evidence = normalize_backtest(_backtest())
            decision = evaluate_simulation(evidence)

            with self.assertRaisesRegex(ValueError, "received cash"):
                record_trading_simulation_result(
                    audit_ledger=audit,
                    experiment_ledger=experiments,
                    evidence=replace(evidence, proves_received_cash=True),
                    decision=decision,
                )

            with self.assertRaisesRegex(ValueError, "live execution"):
                record_trading_simulation_result(
                    audit_ledger=audit,
                    experiment_ledger=experiments,
                    evidence=evidence,
                    decision=replace(decision, may_enter_live_execution=True),
                )


if __name__ == "__main__":
    unittest.main()
