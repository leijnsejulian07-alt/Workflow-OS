import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from workflow_os.alpaca_paper_equity import build_alpaca_paper_equity_curve
from workflow_os.alpaca_paper_evidence import record_alpaca_paper_order_outcome_evidence
from workflow_os.alpaca_paper_execution_costs import evaluate_paper_execution_economics
from workflow_os.alpaca_paper_fill_provenance import verify_alpaca_paper_curve_fill_provenance
from workflow_os.alpaca_paper_order_outcome import AlpacaPaperOrderOutcome
from workflow_os.alpaca_paper_position_accounting import match_closed_long_paper_position
from workflow_os.alpaca_paper_position_evidence import record_alpaca_paper_position_evidence
from workflow_os.alpaca_paper_runtime import AlpacaPaperStrategyPolicy
from workflow_os.audit import AuditRevenueLedger


class AlpacaPaperFillProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "audit.db"
        self.audit = AuditRevenueLedger(self.path)
        self.policy = AlpacaPaperStrategyPolicy(strategy_id="minute-body-v1")

    def tearDown(self):
        self.tmp.cleanup()

    def _outcome(self, *, client_order_id, side, price, filled_at):
        filled_at_dt = datetime.fromisoformat(filled_at.replace("Z", "+00:00")).astimezone(timezone.utc)
        return AlpacaPaperOrderOutcome(
            external_order_id=f"external-{client_order_id}",
            client_order_id=client_order_id,
            symbol="AAPL",
            side=side,
            status="filled",
            ordered_qty=Decimal("2"),
            filled_qty=Decimal("2"),
            filled_avg_price=Decimal(price),
            submitted_at=filled_at_dt.replace(second=0),
            filled_at=filled_at_dt,
            terminal=True,
        )

    def _record_outcome(self, outcome, observed_at):
        record_alpaca_paper_order_outcome_evidence(
            audit_ledger=self.audit,
            account_id="paper-account",
            policy=self.policy,
            outcome=outcome,
            occurred_at=observed_at,
        )

    def _build_curve(self, *, opening, closing, position_observed_at):
        position = match_closed_long_paper_position(
            opening=evaluate_paper_execution_economics(outcome=opening, reference_price=opening.filled_avg_price),
            closing=evaluate_paper_execution_economics(outcome=closing, reference_price=closing.filled_avg_price),
        )
        record_alpaca_paper_position_evidence(
            audit_ledger=self.audit,
            account_id="paper-account",
            strategy_policy=self.policy,
            position=position,
            occurred_at=position_observed_at,
        )
        return build_alpaca_paper_equity_curve(
            audit_ledger=self.audit,
            strategy_policy=self.policy,
            starting_equity_usd="1000",
        )

    def test_uses_actual_fill_times_not_delayed_observation_time(self):
        opening = self._outcome(
            client_order_id="trade-open",
            side="buy",
            price="100",
            filled_at="2026-09-11T10:00:01Z",
        )
        closing = self._outcome(
            client_order_id="trade-close",
            side="sell",
            price="110",
            filled_at="2026-09-11T10:30:01Z",
        )
        self._record_outcome(opening, "2026-09-11T12:00:00Z")
        self._record_outcome(closing, "2026-09-11T12:01:00Z")
        curve = self._build_curve(
            opening=opening,
            closing=closing,
            position_observed_at="2026-09-11T12:02:00Z",
        )

        provenance = verify_alpaca_paper_curve_fill_provenance(
            audit_ledger=self.audit,
            strategy_policy=self.policy,
            curve=curve,
        )

        self.assertEqual(len(provenance), 1)
        self.assertEqual(provenance[0].opening_filled_at, "2026-09-11T10:00:01+00:00")
        self.assertEqual(provenance[0].closing_filled_at, "2026-09-11T10:30:01+00:00")
        self.assertNotEqual(curve.points[0].occurred_at, provenance[0].closing_filled_at)

    def test_missing_exact_fill_price_provenance_fails_closed(self):
        opening = self._outcome(
            client_order_id="price-open",
            side="buy",
            price="100",
            filled_at="2026-09-11T10:00:01Z",
        )
        closing_for_position = self._outcome(
            client_order_id="price-close",
            side="sell",
            price="110",
            filled_at="2026-09-11T10:30:01Z",
        )
        closing_evidence = self._outcome(
            client_order_id="price-close",
            side="sell",
            price="109",
            filled_at="2026-09-11T10:30:01Z",
        )
        self._record_outcome(opening, "2026-09-11T12:00:00Z")
        self._record_outcome(closing_evidence, "2026-09-11T12:01:00Z")
        curve = self._build_curve(
            opening=opening,
            closing=closing_for_position,
            position_observed_at="2026-09-11T12:02:00Z",
        )

        with self.assertRaisesRegex(ValueError, "matching closing fill provenance"):
            verify_alpaca_paper_curve_fill_provenance(
                audit_ledger=self.audit,
                strategy_policy=self.policy,
                curve=curve,
            )

    def test_fill_chronology_must_be_open_then_close(self):
        opening = self._outcome(
            client_order_id="time-open",
            side="buy",
            price="100",
            filled_at="2026-09-11T10:30:01Z",
        )
        closing = self._outcome(
            client_order_id="time-close",
            side="sell",
            price="110",
            filled_at="2026-09-11T10:00:01Z",
        )
        self._record_outcome(opening, "2026-09-11T12:00:00Z")
        self._record_outcome(closing, "2026-09-11T12:01:00Z")
        curve = self._build_curve(
            opening=opening,
            closing=closing,
            position_observed_at="2026-09-11T12:02:00Z",
        )

        with self.assertRaisesRegex(ValueError, "fill chronology"):
            verify_alpaca_paper_curve_fill_provenance(
                audit_ledger=self.audit,
                strategy_policy=self.policy,
                curve=curve,
            )


if __name__ == "__main__":
    unittest.main()
