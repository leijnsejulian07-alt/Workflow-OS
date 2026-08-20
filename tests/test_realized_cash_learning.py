import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.performance import decide_from_realized_cash


class RealizedCashLearningTests(unittest.TestCase):
    def test_invalid_evidence_pauses_fail_closed(self):
        for value in (None, -1, math.inf, math.nan, "bad"):
            decision = decide_from_realized_cash(
                "op-1", realized_cash_eur=value, reconciled_cost_eur=0, sample_count=1
            )
            self.assertEqual(decision.action, "PAUSE")
            self.assertIn("REALIZED_EVIDENCE_UNKNOWN_OR_INVALID", decision.reasons)

    def test_no_samples_does_not_scale_forecast_only_evidence(self):
        decision = decide_from_realized_cash(
            "op-1", realized_cash_eur=1000, reconciled_cost_eur=0, sample_count=0
        )
        self.assertEqual(decision.action, "PAUSE")

    def test_negative_realized_margin_kills(self):
        decision = decide_from_realized_cash(
            "op-1", realized_cash_eur=10, reconciled_cost_eur=20, sample_count=1
        )
        self.assertEqual(decision.action, "KILL")
        self.assertEqual(decision.realized_profit_eur, -10)

    def test_positive_early_sample_keeps_without_scaling(self):
        decision = decide_from_realized_cash(
            "op-1", realized_cash_eur=20, reconciled_cost_eur=5, sample_count=1
        )
        self.assertEqual(decision.action, "KEEP")

    def test_scale_requires_sample_and_profit_floor(self):
        below_samples = decide_from_realized_cash(
            "op-1", realized_cash_eur=100, reconciled_cost_eur=10, sample_count=2
        )
        below_profit = decide_from_realized_cash(
            "op-1", realized_cash_eur=30, reconciled_cost_eur=10, sample_count=3
        )
        proven = decide_from_realized_cash(
            "op-1", realized_cash_eur=100, reconciled_cost_eur=10, sample_count=3
        )
        self.assertEqual(below_samples.action, "KEEP")
        self.assertEqual(below_profit.action, "KEEP")
        self.assertEqual(proven.action, "SCALE")
        self.assertIn("PROVEN_REALIZED_PROFIT", proven.reasons)

    def test_boolean_sample_count_is_rejected(self):
        decision = decide_from_realized_cash(
            "op-1", realized_cash_eur=100, reconciled_cost_eur=10, sample_count=True
        )
        self.assertEqual(decision.action, "PAUSE")


if __name__ == "__main__":
    unittest.main()
