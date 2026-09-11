import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from workflow_os.alpaca_paper_equity import build_alpaca_paper_equity_curve
from workflow_os.alpaca_paper_evidence import record_alpaca_paper_order_outcome_evidence
from workflow_os.alpaca_paper_execution_costs import evaluate_paper_execution_economics
from workflow_os.alpaca_paper_fill_provenance import verify_alpaca_paper_curve_fill_provenance
from workflow_os.alpaca_paper_funded_readiness import (
    AlpacaPaperValidationWindow,
    build_alpaca_paper_validation_window,
    evaluate_alpaca_funded_readiness,
)
from workflow_os.alpaca_paper_learning_adapter import AlpacaPaperLearningContext
from workflow_os.alpaca_paper_order_outcome import AlpacaPaperOrderOutcome
from workflow_os.alpaca_paper_position_accounting import match_closed_long_paper_position
from workflow_os.alpaca_paper_position_evidence import record_alpaca_paper_position_evidence
from workflow_os.alpaca_paper_runtime import AlpacaPaperStrategyPolicy
from workflow_os.audit import AuditRevenueLedger
from workflow_os.trading_paper_learning import PaperLearningPolicy


class AlpacaPaperFundedReadinessReverificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.audit = AuditRevenueLedger(Path(self.tmp.name) / "audit.db")
        self.strategy_policy = AlpacaPaperStrategyPolicy(strategy_id="alpha")

    def tearDown(self):
        self.tmp.cleanup()

    def _outcome(self, *, client_order_id: str, side: str, price: str, filled_at: str) -> AlpacaPaperOrderOutcome:
        filled = datetime.fromisoformat(filled_at.replace("Z", "+00:00")).astimezone(timezone.utc)
        return AlpacaPaperOrderOutcome(
            external_order_id=f"external-{client_order_id}",
            client_order_id=client_order_id,
            symbol="AAPL",
            side=side,
            status="filled",
            ordered_qty=Decimal("2"),
            filled_qty=Decimal("2"),
            filled_avg_price=Decimal(price),
            submitted_at=filled.replace(second=0),
            filled_at=filled,
            terminal=True,
        )

    def _evidence_fixture(self):
        opening = self._outcome(
            client_order_id="open-forge",
            side="buy",
            price="100",
            filled_at="2026-08-10T10:00:00Z",
        )
        closing = self._outcome(
            client_order_id="close-forge",
            side="sell",
            price="110",
            filled_at="2026-08-10T10:30:00Z",
        )
        for outcome in (opening, closing):
            record_alpaca_paper_order_outcome_evidence(
                audit_ledger=self.audit,
                account_id="paper-account",
                policy=self.strategy_policy,
                outcome=outcome,
                occurred_at="2026-08-11T01:00:00Z",
            )
        position = match_closed_long_paper_position(
            opening=evaluate_paper_execution_economics(outcome=opening, reference_price="100"),
            closing=evaluate_paper_execution_economics(outcome=closing, reference_price="110"),
        )
        record_alpaca_paper_position_evidence(
            audit_ledger=self.audit,
            account_id="paper-account",
            strategy_policy=self.strategy_policy,
            position=position,
            occurred_at="2026-08-11T01:00:00Z",
        )
        curve = build_alpaca_paper_equity_curve(
            audit_ledger=self.audit,
            strategy_policy=self.strategy_policy,
            starting_equity_usd="1000",
        )
        context = AlpacaPaperLearningContext(
            strategy_family="momentum",
            strategy_version="v1",
            validation_start="2026-08-10T00:00:00Z",
            validation_end="2026-08-11T00:00:00Z",
            execution_error_count=0,
            ambiguous_side_effect_count=0,
            market_regimes=("trend", "range"),
            observed_at="2026-08-11T01:00:00Z",
        )
        policy = PaperLearningPolicy(
            min_validation_trades=1,
            min_validation_days=1,
            min_market_regimes=2,
            max_drawdown_pct=8.0,
            max_execution_error_rate=0.02,
            min_green_windows_for_funded_ready=1,
            min_total_oos_days_for_funded_ready=1,
        )
        return curve, context, policy

    def test_evaluator_reverifies_underscore_constructed_window_against_ledger(self):
        curve, context, policy = self._evidence_fixture()
        real_provenance = verify_alpaca_paper_curve_fill_provenance(
            audit_ledger=self.audit,
            strategy_policy=self.strategy_policy,
            curve=curve,
        )
        forged_provenance = (
            replace(real_provenance[0], opening_filled_at="2026-08-10T11:00:00+00:00"),
        )
        forged_window = AlpacaPaperValidationWindow._from_verified_provenance(
            audit_ledger=self.audit,
            strategy_policy=self.strategy_policy,
            curve=curve,
            context=context,
            train_start="2026-08-01T00:00:00Z",
            train_end="2026-08-10T00:00:00Z",
            fill_provenance=forged_provenance,
        )

        with self.assertRaisesRegex(
            ValueError,
            "validation window provenance does not match immutable ledger evidence",
        ):
            evaluate_alpaca_funded_readiness((forged_window,), policy)

    def test_evaluator_revalidates_mutated_oos_boundaries_against_real_fills(self):
        curve, context, policy = self._evidence_fixture()
        window = build_alpaca_paper_validation_window(
            audit_ledger=self.audit,
            strategy_policy=self.strategy_policy,
            curve=curve,
            context=context,
            train_start="2026-08-01T00:00:00Z",
            train_end="2026-08-10T00:00:00Z",
        )
        mutated_context = replace(
            context,
            validation_start="2026-08-10T10:15:00Z",
        )
        object.__setattr__(window, "context", mutated_context)

        with self.assertRaisesRegex(
            ValueError,
            "paper position fills fall outside its validation window",
        ):
            evaluate_alpaca_funded_readiness((window,), policy)


if __name__ == "__main__":
    unittest.main()
