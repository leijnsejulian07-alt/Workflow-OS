import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from workflow_os.alpaca_paper_equity import build_alpaca_paper_equity_curve
from workflow_os.alpaca_paper_evidence import record_alpaca_paper_order_outcome_evidence
from workflow_os.alpaca_paper_execution_costs import evaluate_paper_execution_economics
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


class AlpacaPaperFundedReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmpdirs: list[tempfile.TemporaryDirectory[str]] = []
        self.policy = AlpacaPaperStrategyPolicy(strategy_id="alpha")

    def tearDown(self):
        for tmp in self.tmpdirs:
            tmp.cleanup()

    def _ledger(self) -> AuditRevenueLedger:
        tmp = tempfile.TemporaryDirectory()
        self.tmpdirs.append(tmp)
        return AuditRevenueLedger(Path(tmp.name) / "audit.db")

    def _make_outcome(self, *, client_order_id: str, side: str, price: str, filled_at: str) -> AlpacaPaperOrderOutcome:
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

    def _context(self, *, start: str, end: str, observed: str, version: str = "v1") -> AlpacaPaperLearningContext:
        return AlpacaPaperLearningContext(
            strategy_family="momentum",
            strategy_version=version,
            validation_start=start,
            validation_end=end,
            execution_error_count=0,
            ambiguous_side_effect_count=0,
            market_regimes=("trend", "range"),
            observed_at=observed,
        )

    def _window(
        self,
        *,
        suffix: str,
        train_start: str,
        train_end: str,
        start: str,
        end: str,
        opening_fill: str,
        closing_fill: str,
        evidence_observed_at: str,
        opening_price: str = "100",
        closing_price: str = "110",
        policy: AlpacaPaperStrategyPolicy | None = None,
        version: str = "v1",
    ) -> AlpacaPaperValidationWindow:
        policy = policy or self.policy
        audit = self._ledger()
        opening = self._make_outcome(
            client_order_id=f"open-{suffix}",
            side="buy",
            price=opening_price,
            filled_at=opening_fill,
        )
        closing = self._make_outcome(
            client_order_id=f"close-{suffix}",
            side="sell",
            price=closing_price,
            filled_at=closing_fill,
        )
        for outcome, observed_at in (
            (opening, evidence_observed_at),
            (closing, evidence_observed_at),
        ):
            record_alpaca_paper_order_outcome_evidence(
                audit_ledger=audit,
                account_id="paper-account",
                policy=policy,
                outcome=outcome,
                occurred_at=observed_at,
            )
        position = match_closed_long_paper_position(
            opening=evaluate_paper_execution_economics(
                outcome=opening,
                reference_price=opening.filled_avg_price,
            ),
            closing=evaluate_paper_execution_economics(
                outcome=closing,
                reference_price=closing.filled_avg_price,
            ),
        )
        record_alpaca_paper_position_evidence(
            audit_ledger=audit,
            account_id="paper-account",
            strategy_policy=policy,
            position=position,
            occurred_at=evidence_observed_at,
        )
        curve = build_alpaca_paper_equity_curve(
            audit_ledger=audit,
            strategy_policy=policy,
            starting_equity_usd="1000",
        )
        return build_alpaca_paper_validation_window(
            audit_ledger=audit,
            strategy_policy=policy,
            curve=curve,
            context=self._context(start=start, end=end, observed=evidence_observed_at, version=version),
            train_start=train_start,
            train_end=train_end,
        )

    def _policy(self) -> PaperLearningPolicy:
        return PaperLearningPolicy(
            min_validation_trades=1,
            min_validation_days=1,
            min_market_regimes=2,
            max_drawdown_pct=8.0,
            max_execution_error_rate=0.02,
            min_green_windows_for_funded_ready=2,
            min_total_oos_days_for_funded_ready=2,
        )

    def test_delayed_evidence_after_validation_end_uses_real_fill_times(self):
        window = self._window(
            suffix="delayed",
            train_start="2026-08-01T00:00:00Z",
            train_end="2026-08-10T00:00:00Z",
            start="2026-08-10T00:00:00Z",
            end="2026-08-11T00:00:00Z",
            opening_fill="2026-08-10T10:00:00Z",
            closing_fill="2026-08-10T10:30:00Z",
            evidence_observed_at="2026-08-12T12:00:00Z",
        )
        self.assertGreater(window.curve.points[0].occurred_at, window.context.validation_end)
        self.assertEqual(window.fill_provenance[0].opening_filled_at, "2026-08-10T10:00:00+00:00")

    def test_sustained_non_overlapping_windows_reach_evidence_only_funded_ready(self):
        windows = (
            self._window(
                suffix="one",
                train_start="2026-08-01T00:00:00Z",
                train_end="2026-08-10T00:00:00Z",
                start="2026-08-10T00:00:00Z",
                end="2026-08-11T00:00:00Z",
                opening_fill="2026-08-10T10:00:00Z",
                closing_fill="2026-08-10T10:30:00Z",
                evidence_observed_at="2026-08-11T01:00:00Z",
            ),
            self._window(
                suffix="two",
                train_start="2026-08-01T00:00:00Z",
                train_end="2026-08-11T00:00:00Z",
                start="2026-08-11T00:00:00Z",
                end="2026-08-12T00:00:00Z",
                opening_fill="2026-08-11T10:00:00Z",
                closing_fill="2026-08-11T10:30:00Z",
                evidence_observed_at="2026-08-12T01:00:00Z",
            ),
        )
        decision = evaluate_alpaca_funded_readiness(windows, self._policy())
        self.assertEqual(decision.state, "FUNDED_READY")
        self.assertEqual(len(decision.qualifying_window_fingerprints), 2)
        self.assertFalse(decision.may_purchase_funded_account)
        self.assertFalse(decision.may_request_live_credentials)
        self.assertFalse(decision.may_enter_live_execution)

    def test_opening_fill_before_validation_start_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "fills fall outside"):
            self._window(
                suffix="early-open",
                train_start="2026-08-01T00:00:00Z",
                train_end="2026-08-10T00:00:00Z",
                start="2026-08-10T00:00:00Z",
                end="2026-08-11T00:00:00Z",
                opening_fill="2026-08-09T23:59:59Z",
                closing_fill="2026-08-10T10:30:00Z",
                evidence_observed_at="2026-08-11T01:00:00Z",
            )

    def test_closing_fill_at_validation_end_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "fills fall outside"):
            self._window(
                suffix="late-close",
                train_start="2026-08-01T00:00:00Z",
                train_end="2026-08-10T00:00:00Z",
                start="2026-08-10T00:00:00Z",
                end="2026-08-11T00:00:00Z",
                opening_fill="2026-08-10T10:00:00Z",
                closing_fill="2026-08-11T00:00:00Z",
                evidence_observed_at="2026-08-11T01:00:00Z",
            )

    def test_overlapping_oos_windows_do_not_reach_funded_ready(self):
        windows = (
            self._window(
                suffix="overlap-one",
                train_start="2026-08-01T00:00:00Z",
                train_end="2026-08-10T00:00:00Z",
                start="2026-08-10T00:00:00Z",
                end="2026-08-12T00:00:00Z",
                opening_fill="2026-08-10T10:00:00Z",
                closing_fill="2026-08-10T10:30:00Z",
                evidence_observed_at="2026-08-12T01:00:00Z",
            ),
            self._window(
                suffix="overlap-two",
                train_start="2026-08-01T00:00:00Z",
                train_end="2026-08-11T00:00:00Z",
                start="2026-08-11T00:00:00Z",
                end="2026-08-13T00:00:00Z",
                opening_fill="2026-08-11T10:00:00Z",
                closing_fill="2026-08-11T10:30:00Z",
                evidence_observed_at="2026-08-13T01:00:00Z",
            ),
        )
        decision = evaluate_alpaca_funded_readiness(windows, self._policy())
        self.assertEqual(decision.state, "PAPER_AMBER")
        self.assertEqual(decision.reasons, ("QUALIFYING_OOS_WINDOWS_OVERLAP",))

    def test_exact_strategy_policy_fingerprint_must_remain_stable(self):
        changed_policy = AlpacaPaperStrategyPolicy(strategy_id="alpha", minimum_body_bps=6.0)
        windows = (
            self._window(
                suffix="policy-one",
                train_start="2026-08-01T00:00:00Z",
                train_end="2026-08-10T00:00:00Z",
                start="2026-08-10T00:00:00Z",
                end="2026-08-11T00:00:00Z",
                opening_fill="2026-08-10T10:00:00Z",
                closing_fill="2026-08-10T10:30:00Z",
                evidence_observed_at="2026-08-11T01:00:00Z",
            ),
            self._window(
                suffix="policy-two",
                train_start="2026-08-01T00:00:00Z",
                train_end="2026-08-11T00:00:00Z",
                start="2026-08-11T00:00:00Z",
                end="2026-08-12T00:00:00Z",
                opening_fill="2026-08-11T10:00:00Z",
                closing_fill="2026-08-11T10:30:00Z",
                evidence_observed_at="2026-08-12T01:00:00Z",
                policy=changed_policy,
            ),
        )
        decision = evaluate_alpaca_funded_readiness(windows, self._policy())
        self.assertEqual(decision.state, "PAPER_AMBER")
        self.assertEqual(decision.reasons, ("GREEN_WINDOWS_NOT_FROM_ONE_EXACT_STRATEGY_POLICY",))

    def test_strategy_version_must_remain_stable_across_qualifying_windows(self):
        windows = (
            self._window(
                suffix="version-one",
                train_start="2026-08-01T00:00:00Z",
                train_end="2026-08-10T00:00:00Z",
                start="2026-08-10T00:00:00Z",
                end="2026-08-11T00:00:00Z",
                opening_fill="2026-08-10T10:00:00Z",
                closing_fill="2026-08-10T10:30:00Z",
                evidence_observed_at="2026-08-11T01:00:00Z",
            ),
            self._window(
                suffix="version-two",
                train_start="2026-08-01T00:00:00Z",
                train_end="2026-08-11T00:00:00Z",
                start="2026-08-11T00:00:00Z",
                end="2026-08-12T00:00:00Z",
                opening_fill="2026-08-11T10:00:00Z",
                closing_fill="2026-08-11T10:30:00Z",
                evidence_observed_at="2026-08-12T01:00:00Z",
                version="v2",
            ),
        )
        decision = evaluate_alpaca_funded_readiness(windows, self._policy())
        self.assertEqual(decision.state, "PAPER_AMBER")
        self.assertEqual(decision.reasons, ("GREEN_WINDOWS_NOT_FROM_ONE_STABLE_STRATEGY_VERSION",))

    def test_red_execution_derived_window_blocks_readiness(self):
        windows = (
            self._window(
                suffix="red",
                train_start="2026-08-01T00:00:00Z",
                train_end="2026-08-10T00:00:00Z",
                start="2026-08-10T00:00:00Z",
                end="2026-08-11T00:00:00Z",
                opening_fill="2026-08-10T10:00:00Z",
                closing_fill="2026-08-10T10:30:00Z",
                evidence_observed_at="2026-08-11T01:00:00Z",
                closing_price="90",
            ),
            self._window(
                suffix="green",
                train_start="2026-08-01T00:00:00Z",
                train_end="2026-08-11T00:00:00Z",
                start="2026-08-11T00:00:00Z",
                end="2026-08-12T00:00:00Z",
                opening_fill="2026-08-11T10:00:00Z",
                closing_fill="2026-08-11T10:30:00Z",
                evidence_observed_at="2026-08-12T01:00:00Z",
            ),
        )
        decision = evaluate_alpaca_funded_readiness(windows, self._policy())
        self.assertEqual(decision.state, "PAPER_RED")
        self.assertIn("NON_POSITIVE_NET_PAPER_PNL", decision.reasons)

    def test_training_and_validation_windows_may_not_overlap(self):
        with self.assertRaisesRegex(ValueError, "chronological and non-overlapping"):
            self._window(
                suffix="train-overlap",
                train_start="2026-08-01T00:00:00Z",
                train_end="2026-08-10T12:00:00Z",
                start="2026-08-10T00:00:00Z",
                end="2026-08-11T00:00:00Z",
                opening_fill="2026-08-10T13:00:00Z",
                closing_fill="2026-08-10T13:30:00Z",
                evidence_observed_at="2026-08-11T01:00:00Z",
            )

    def test_validation_window_cannot_be_constructed_from_caller_forged_provenance(self):
        with self.assertRaises(TypeError):
            AlpacaPaperValidationWindow(
                curve=object(),
                context=object(),
                train_start="2026-08-01T00:00:00Z",
                train_end="2026-08-10T00:00:00Z",
                fill_provenance=(),
            )

    def test_fabricated_curve_pnl_or_costs_fail_before_readiness(self):
        audit = self._ledger()
        opening = self._make_outcome(
            client_order_id="open-tamper",
            side="buy",
            price="100",
            filled_at="2026-08-10T10:00:00Z",
        )
        closing = self._make_outcome(
            client_order_id="close-tamper",
            side="sell",
            price="110",
            filled_at="2026-08-10T10:30:00Z",
        )
        for outcome in (opening, closing):
            record_alpaca_paper_order_outcome_evidence(
                audit_ledger=audit,
                account_id="paper-account",
                policy=self.policy,
                outcome=outcome,
                occurred_at="2026-08-11T01:00:00Z",
            )
        position = match_closed_long_paper_position(
            opening=evaluate_paper_execution_economics(outcome=opening, reference_price="100"),
            closing=evaluate_paper_execution_economics(outcome=closing, reference_price="110"),
        )
        record_alpaca_paper_position_evidence(
            audit_ledger=audit,
            account_id="paper-account",
            strategy_policy=self.policy,
            position=position,
            occurred_at="2026-08-11T01:00:00Z",
        )
        curve = build_alpaca_paper_equity_curve(
            audit_ledger=audit,
            strategy_policy=self.policy,
            starting_equity_usd="1000",
        )
        context = self._context(
            start="2026-08-10T00:00:00Z",
            end="2026-08-11T00:00:00Z",
            observed="2026-08-11T01:00:00Z",
        )
        tampered_point = replace(
            curve.points[0],
            paper_realized_pnl_usd=curve.points[0].paper_realized_pnl_usd + Decimal("1"),
        )
        with self.assertRaisesRegex(ValueError, "pnl does not match"):
            build_alpaca_paper_validation_window(
                audit_ledger=audit,
                strategy_policy=self.policy,
                curve=replace(curve, points=(tampered_point,)),
                context=context,
                train_start="2026-08-01T00:00:00Z",
                train_end="2026-08-10T00:00:00Z",
            )
        with self.assertRaisesRegex(ValueError, "modeled costs do not match"):
            build_alpaca_paper_validation_window(
                audit_ledger=audit,
                strategy_policy=self.policy,
                curve=replace(
                    curve,
                    modeled_execution_costs_usd=curve.modeled_execution_costs_usd + Decimal("1"),
                ),
                context=context,
                train_start="2026-08-01T00:00:00Z",
                train_end="2026-08-10T00:00:00Z",
            )


if __name__ == "__main__":
    unittest.main()
